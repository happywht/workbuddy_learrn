from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from ..tracing import inject_trace_context


HUB_EVENT_KEY = "com.workbuddy.hub"


class AgentTeamsError(RuntimeError):
    """A controlled failure from the AgentTeams or Matrix boundary."""

    def __init__(self, code: str, provider_status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.provider_status = provider_status


def parse_mxc_uri(mxc_uri: str) -> tuple[str, str]:
    parsed = urlsplit(mxc_uri)
    media_id = parsed.path.removeprefix("/")
    if (
        parsed.scheme != "mxc"
        or not parsed.netloc
        or not media_id
        or "/" in media_id
        or parsed.query
        or parsed.fragment
    ):
        raise AgentTeamsError("agentteams_matrix_media_uri_invalid")
    return parsed.netloc, media_id


class AgentTeamsControllerClient:
    """Read AgentTeams resources through its real Controller API."""

    def __init__(
        self,
        base_url: str | None,
        token: str | None = None,
        timeout_seconds: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.token = token
        self.timeout_seconds = timeout_seconds
        self._client = client or httpx.Client(
            timeout=timeout_seconds,
            event_hooks={"request": [inject_trace_context]},
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def close(self) -> None:
        self._client.close()

    def _headers(self, actor_id: str) -> dict[str, str]:
        headers = {"X-Actor-Id": actor_id}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method: str, path: str, actor_id: str) -> dict[str, Any]:
        if not self.base_url:
            raise AgentTeamsError("agentteams_controller_not_configured")
        try:
            response = self._client.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(actor_id),
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise AgentTeamsError("agentteams_controller_unavailable") from exc
        if response.status_code in (401, 403):
            raise AgentTeamsError("agentteams_controller_auth_failed", response.status_code)
        if response.status_code == 404:
            raise AgentTeamsError("agentteams_team_not_found", response.status_code)
        if response.status_code >= 500:
            raise AgentTeamsError("agentteams_controller_unavailable", response.status_code)
        if response.status_code >= 400:
            raise AgentTeamsError("agentteams_controller_request_rejected", response.status_code)
        payload = response.json()
        if not isinstance(payload, dict):
            raise AgentTeamsError("agentteams_controller_invalid_response", response.status_code)
        return payload

    def teams(self, actor_id: str) -> dict[str, Any]:
        return self._request("GET", "/api/v1/teams", actor_id)

    def team(self, actor_id: str, team_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/teams/{quote(team_id, safe='')}", actor_id)


class MatrixClient:
    """Minimal Matrix Client-Server API used by the Hub connector.

    AgentTeams owns room provisioning. The Hub only discovers joined rooms,
    sends idempotent events, and performs incremental sync.
    """

    def __init__(
        self,
        homeserver_url: str | None,
        access_token: str | None,
        user_id: str | None = None,
        timeout_seconds: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.homeserver_url = homeserver_url.rstrip("/") if homeserver_url else None
        self.access_token = access_token
        self.user_id = user_id
        self.timeout_seconds = timeout_seconds
        self._client = client or httpx.Client(
            timeout=timeout_seconds,
            event_hooks={"request": [inject_trace_context]},
        )

    @property
    def configured(self) -> bool:
        return bool(self.homeserver_url and self.access_token)

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.configured:
            raise AgentTeamsError("agentteams_matrix_not_configured")
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self.access_token}"
        request_timeout_seconds = kwargs.pop("request_timeout_seconds", self.timeout_seconds)
        try:
            response = self._client.request(
                method,
                f"{self.homeserver_url}{path}",
                headers=headers,
                timeout=request_timeout_seconds,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise AgentTeamsError("agentteams_matrix_unavailable") from exc
        if response.status_code in (401, 403):
            raise AgentTeamsError("agentteams_matrix_auth_failed", response.status_code)
        if response.status_code >= 500:
            raise AgentTeamsError("agentteams_matrix_unavailable", response.status_code)
        if response.status_code >= 400:
            raise AgentTeamsError("agentteams_matrix_request_rejected", response.status_code)
        payload = response.json()
        if not isinstance(payload, dict):
            raise AgentTeamsError("agentteams_matrix_invalid_response", response.status_code)
        return payload

    def whoami(self) -> str:
        payload = self._request("GET", "/_matrix/client/v3/account/whoami")
        actual_user_id = str(payload.get("user_id") or "")
        if not actual_user_id:
            raise AgentTeamsError("agentteams_matrix_user_id_missing")
        if self.user_id and self.user_id != actual_user_id:
            raise AgentTeamsError("agentteams_matrix_user_mismatch")
        return actual_user_id

    def joined_rooms(self) -> set[str]:
        payload = self._request("GET", "/_matrix/client/v3/joined_rooms")
        rooms = payload.get("joined_rooms")
        if not isinstance(rooms, list):
            raise AgentTeamsError("agentteams_matrix_invalid_response")
        return {str(room_id) for room_id in rooms if room_id}

    def sync(
        self, room_id: str, since: str | None = None, timeout_ms: int = 0
    ) -> dict[str, Any]:
        timeout_ms = max(0, min(timeout_ms, 25_000))
        room_filter = {
            "room": {
                "rooms": [room_id],
                "timeline": {"limit": 50},
                "state": {"lazy_load_members": True},
            }
        }
        params: dict[str, str | int] = {
            "timeout": timeout_ms,
            "full_state": "false",
            "filter": json.dumps(room_filter, separators=(",", ":")),
        }
        if since:
            params["since"] = since
        payload = self._request(
            "GET",
            "/_matrix/client/v3/sync",
            params=params,
            request_timeout_seconds=max(self.timeout_seconds, timeout_ms / 1000 + 5),
        )
        joined = payload.get("rooms", {}).get("join", {})
        room = joined.get(room_id, {}) if isinstance(joined, dict) else {}
        timeline = room.get("timeline", {}) if isinstance(room, dict) else {}
        events = timeline.get("events", []) if isinstance(timeline, dict) else []
        return {
            "events": events if isinstance(events, list) else [],
            "next_cursor": payload.get("next_batch"),
        }

    def send_text(self, room_id: str, transaction_id: str, content: dict[str, Any]) -> dict[str, Any]:
        encoded_room = quote(room_id, safe="")
        encoded_txn = quote(transaction_id, safe="")
        return self._request(
            "PUT",
            f"/_matrix/client/v3/rooms/{encoded_room}/send/m.room.message/{encoded_txn}",
            json=content,
        )

    def download_media(self, mxc_uri: str, max_bytes: int) -> "MatrixMedia":
        if not self.configured:
            raise AgentTeamsError("agentteams_matrix_not_configured")
        server_name, media_id = parse_mxc_uri(mxc_uri)
        if max_bytes < 1:
            raise AgentTeamsError("agentteams_matrix_media_limit_invalid")
        path = (
            "/_matrix/media/v3/download/"
            f"{quote(server_name, safe='')}/{quote(media_id, safe='')}"
        )
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept-Encoding": "identity",
        }
        try:
            with self._client.stream(
                "GET",
                f"{self.homeserver_url}{path}",
                headers=headers,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code in (401, 403):
                    raise AgentTeamsError("agentteams_matrix_auth_failed", response.status_code)
                if response.status_code == 404:
                    raise AgentTeamsError("agentteams_matrix_media_not_found", response.status_code)
                if response.status_code == 413:
                    raise AgentTeamsError("agentteams_matrix_media_too_large", response.status_code)
                if response.status_code >= 500:
                    raise AgentTeamsError("agentteams_matrix_unavailable", response.status_code)
                if response.status_code < 200 or response.status_code >= 300:
                    raise AgentTeamsError("agentteams_matrix_media_request_rejected", response.status_code)
                content_length = response.headers.get("content-length")
                declared_length: int | None = None
                if content_length:
                    try:
                        declared_length = int(content_length)
                    except ValueError as exc:
                        raise AgentTeamsError("agentteams_matrix_media_invalid_response") from exc
                    if declared_length < 0:
                        raise AgentTeamsError("agentteams_matrix_media_invalid_response")
                    if declared_length > max_bytes:
                        raise AgentTeamsError("agentteams_matrix_media_too_large", response.status_code)
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes(chunk_size=64 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        raise AgentTeamsError("agentteams_matrix_media_too_large", response.status_code)
                    chunks.append(chunk)
                if declared_length is not None and declared_length != total:
                    raise AgentTeamsError("agentteams_matrix_media_invalid_response")
                return MatrixMedia(
                    content=b"".join(chunks),
                    content_type=response.headers.get("content-type", "application/octet-stream"),
                )
        except AgentTeamsError:
            raise
        except httpx.HTTPError as exc:
            raise AgentTeamsError("agentteams_matrix_unavailable") from exc


@dataclass(frozen=True)
class MatrixMedia:
    content: bytes
    content_type: str


@dataclass(frozen=True)
class DispatchTarget:
    room_id: str
    room_kind: str
    leader_matrix_user_id: str | None


def resolve_dispatch_target(
    team: dict[str, Any], matrix_user_id: str, joined_rooms: set[str]
) -> DispatchTarget:
    """Choose the Team Admin-to-Leader room exposed by AgentTeams.

    Team coordinators must mention the Leader in the Team Room, but the pinned
    Controller response does not expose the Leader Matrix ID. Until upstream
    exposes that identity, only the Team Admin path is safely automatable.
    """
    admin = team.get("admin") if isinstance(team.get("admin"), dict) else {}
    leader_dm_room_id = str(team.get("leaderDMRoomID") or "")
    is_team_admin = admin.get("matrixUserId") == matrix_user_id
    if is_team_admin and leader_dm_room_id in joined_rooms:
        return DispatchTarget(leader_dm_room_id, "leader_dm", None)
    raise AgentTeamsError("agentteams_no_joined_dispatch_room")


def build_hub_message(
    *,
    kind: str,
    task_id: str,
    actor_id: str,
    content: str,
    leader_matrix_user_id: str | None = None,
    budget: dict[str, Any] | None = None,
    output_contract: dict[str, Any] | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    marker = f"[WBH:{task_id}]"
    mention = f"{leader_matrix_user_id} " if leader_matrix_user_id else ""
    body = f"{mention}{marker} {content}".strip()
    envelope: dict[str, Any] = {
        "schema": "workbuddy.hub.collaboration.v1",
        "kind": kind,
        "task_id": task_id,
        "actor_id": actor_id,
    }
    if budget:
        envelope["budget"] = budget
    if output_contract:
        envelope["output_contract"] = output_contract
    if attachments:
        envelope["attachments"] = attachments
    if kind == "task.request":
        details = []
        if budget:
            details.append(f"Budget: {json.dumps(budget, ensure_ascii=False, sort_keys=True)}")
        if output_contract:
            details.append(
                f"Output contract: {json.dumps(output_contract, ensure_ascii=False, sort_keys=True)}"
            )
        details.append(f"Keep {marker} in task-specific replies so Hub can correlate them.")
        body = "\n\n".join((body, *details))
    message: dict[str, Any] = {
        "msgtype": "m.text",
        "body": body,
        HUB_EVENT_KEY: envelope,
    }
    if leader_matrix_user_id:
        message["m.mentions"] = {"user_ids": [leader_matrix_user_id]}
    return message


def event_belongs_to_task(event: dict[str, Any], task_id: str) -> bool:
    content = event.get("content")
    if not isinstance(content, dict):
        return False
    envelope = content.get(HUB_EVENT_KEY)
    if isinstance(envelope, dict) and envelope.get("task_id") == task_id:
        return True
    # Models may reformat the WBH prefix or brackets, but the full opaque task
    # id remains unique enough to correlate safely within the dedicated room.
    return task_id in str(content.get("body") or "")


def event_status(event: dict[str, Any]) -> str | None:
    content = event.get("content")
    envelope = content.get(HUB_EVENT_KEY) if isinstance(content, dict) else None
    if not isinstance(envelope, dict) or envelope.get("kind") != "task.status":
        return None
    status = envelope.get("status")
    return str(status) if status else None


def event_artifact(event: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    """Extract metadata from a structured Matrix task artifact event.

    The Hub deliberately does not proxy or verify the file body here. Matrix
    remains the authorization boundary for fetching the referenced MXC object.
    """
    content = event.get("content")
    envelope = content.get(HUB_EVENT_KEY) if isinstance(content, dict) else None
    if not isinstance(envelope, dict):
        return None
    if envelope.get("kind") != "task.artifact" or envelope.get("task_id") != task_id:
        return None
    if content.get("msgtype") != "m.file":
        return None
    mxc_uri = str(content.get("url") or "")
    if not mxc_uri.startswith("mxc://"):
        return None
    event_id = str(event.get("event_id") or "")
    if not event_id:
        return None
    info = content.get("info") if isinstance(content.get("info"), dict) else {}
    size = info.get("size")
    return {
        "artifact_id": event_id,
        "task_id": task_id,
        "name": str(content.get("body") or envelope.get("name") or "unnamed-file"),
        "mxc_uri": mxc_uri,
        "media_type": str(info.get("mimetype") or "application/octet-stream"),
        "size": size if isinstance(size, int) and size >= 0 else None,
        "sha256": str(envelope.get("sha256") or "") or None,
        "purpose": str(envelope.get("purpose") or "result"),
        "sender": str(event.get("sender") or "") or None,
        "origin_server_ts": event.get("origin_server_ts")
        if isinstance(event.get("origin_server_ts"), int)
        else None,
        "verification_status": "metadata_only",
        "content_verified": False,
        "safe_to_execute": False,
    }
