from __future__ import annotations

import json

import httpx
import pytest

from hub_api.integrations.agentteams import (
    HUB_EVENT_KEY,
    AgentTeamsControllerClient,
    AgentTeamsError,
    MatrixClient,
    build_hub_message,
    event_artifact,
    event_belongs_to_task,
    event_status,
    resolve_dispatch_target,
)


PINNED_TEAM = {
    "name": "delivery-team",
    "teamName": "Delivery Team",
    "phase": "Active",
    "admin": {"name": "hub-admin", "matrixUserId": "@hub-admin:matrix.test"},
    "humanMembers": [
        {"name": "coordinator", "matrixUserId": "@coordinator:matrix.test", "role": "coordinator"}
    ],
    "workerMembers": [
        {"name": "delivery-lead", "role": "team_leader"},
        {"name": "delivery-worker", "role": "worker"},
    ],
    "leaderName": "delivery-lead",
    "teamRoomID": "!team:matrix.test",
    "leaderDMRoomID": "!leader-dm:matrix.test",
    "leaderReady": True,
    "readyWorkers": 1,
    "totalWorkers": 1,
}


def test_controller_uses_real_team_routes_and_upstream_shape():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v1/teams":
            return httpx.Response(200, json={"teams": [PINNED_TEAM], "total": 1})
        if request.url.path == "/api/v1/teams/delivery-team":
            return httpx.Response(200, json=PINNED_TEAM)
        return httpx.Response(404)

    client = AgentTeamsControllerClient(
        "http://controller.test",
        token="controller-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.teams("user-1")["total"] == 1
    assert client.team("user-1", "delivery-team")["leaderDMRoomID"] == "!leader-dm:matrix.test"
    assert [request.url.path for request in requests] == [
        "/api/v1/teams",
        "/api/v1/teams/delivery-team",
    ]
    assert all(request.headers["authorization"] == "Bearer controller-token" for request in requests)
    assert all(request.headers["x-actor-id"] == "user-1" for request in requests)
    client.close()


def test_controller_team_id_is_path_encoded():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["raw_path"] = request.url.raw_path
        return httpx.Response(200, json=PINNED_TEAM)

    client = AgentTeamsControllerClient(
        "http://controller.test", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    client.team("user-1", "team/name")
    assert seen["raw_path"] == b"/api/v1/teams/team%2Fname"
    client.close()


def test_matrix_uses_client_server_routes_and_incremental_sync():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/account/whoami"):
            return httpx.Response(200, json={"user_id": "@hub-admin:matrix.test"})
        if request.url.path.endswith("/joined_rooms"):
            return httpx.Response(200, json={"joined_rooms": ["!leader-dm:matrix.test"]})
        if request.url.path.endswith("/sync"):
            return httpx.Response(
                200,
                json={
                    "next_batch": "s1",
                    "rooms": {
                        "join": {
                            "!leader-dm:matrix.test": {
                                "timeline": {"events": [{"event_id": "$reply", "type": "m.room.message"}]}
                            }
                        }
                    },
                },
            )
        return httpx.Response(200, json={"event_id": "$dispatch"})

    client = MatrixClient(
        "http://matrix.test",
        "matrix-token",
        user_id="@hub-admin:matrix.test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.whoami() == "@hub-admin:matrix.test"
    assert client.joined_rooms() == {"!leader-dm:matrix.test"}
    sync = client.sync("!leader-dm:matrix.test", since="s0", timeout_ms=25_000)
    assert sync == {"events": [{"event_id": "$reply", "type": "m.room.message"}], "next_cursor": "s1"}
    sent = client.send_text("!leader-dm:matrix.test", "collab_123", {"msgtype": "m.text", "body": "task"})
    assert sent["event_id"] == "$dispatch"
    sync_request = next(request for request in seen if request.url.path.endswith("/sync"))
    assert sync_request.url.params["since"] == "s0"
    assert sync_request.url.params["timeout"] == "25000"
    assert json.loads(sync_request.url.params["filter"])["room"]["rooms"] == ["!leader-dm:matrix.test"]
    send_request = seen[-1]
    assert send_request.url.raw_path.startswith(
        b"/_matrix/client/v3/rooms/%21leader-dm%3Amatrix.test/send/m.room.message/collab_123"
    )
    assert all(request.headers["authorization"] == "Bearer matrix-token" for request in seen)
    client.close()


def test_matrix_media_download_is_authenticated_encoded_and_limited():
    requests: list[httpx.Request] = []
    content = b"%PDF-1.7\nverified\n"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/too-large"):
            return httpx.Response(200, headers={"Content-Length": "1000"}, content=b"x")
        return httpx.Response(200, headers={"Content-Type": "application/pdf"}, content=content)

    client = MatrixClient(
        "http://matrix.test",
        "matrix-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    media = client.download_media("mxc://matrix.test/media id", max_bytes=1024)
    assert media.content == content
    assert media.content_type == "application/pdf"
    assert requests[0].url.raw_path == b"/_matrix/media/v3/download/matrix.test/media%20id"
    assert requests[0].headers["authorization"] == "Bearer matrix-token"

    with pytest.raises(AgentTeamsError, match="agentteams_matrix_media_too_large"):
        client.download_media("mxc://matrix.test/too-large", max_bytes=10)
    with pytest.raises(AgentTeamsError, match="agentteams_matrix_media_uri_invalid"):
        client.download_media("mxc://matrix.test/nested/path", max_bytes=10)
    client.close()


def test_dispatch_is_limited_to_joined_team_admin_dm():
    target = resolve_dispatch_target(
        PINNED_TEAM,
        "@hub-admin:matrix.test",
        {"!leader-dm:matrix.test", "!team:matrix.test"},
    )
    assert (target.room_id, target.room_kind) == ("!leader-dm:matrix.test", "leader_dm")

    with pytest.raises(AgentTeamsError) as exc_info:
        resolve_dispatch_target(PINNED_TEAM, "@coordinator:matrix.test", {"!team:matrix.test"})
    assert exc_info.value.code == "agentteams_no_joined_dispatch_room"


def test_hub_envelope_is_visible_and_machine_correlatable():
    message = build_hub_message(
        kind="task.request",
        task_id="collab_123",
        actor_id="user-1",
        content="Check the delivery package",
        budget={"minutes": 30},
        output_contract={"type": "report"},
    )
    assert "[WBH:collab_123]" in message["body"]
    assert "Budget:" in message["body"]
    assert "Output contract:" in message["body"]
    assert message[HUB_EVENT_KEY]["kind"] == "task.request"
    event = {"content": message}
    assert event_belongs_to_task(event, "collab_123") is True

    message[HUB_EVENT_KEY] = {
        "schema": "workbuddy.hub.collaboration.v1",
        "kind": "task.status",
        "task_id": "collab_123",
        "status": "running",
    }
    assert event_status(event) == "running"


def test_task_artifact_requires_structured_envelope_and_mxc_uri():
    event = {
        "event_id": "$artifact-1",
        "sender": "@worker:matrix.test",
        "origin_server_ts": 1786168800000,
        "content": {
            "msgtype": "m.file",
            "body": "delivery-report.pdf",
            "url": "mxc://matrix.test/media-1",
            "info": {"mimetype": "application/pdf", "size": 2048},
            HUB_EVENT_KEY: {
                "kind": "task.artifact",
                "task_id": "collab_123",
                "purpose": "result",
                "sha256": "a" * 64,
            },
        },
    }
    artifact = event_artifact(event, "collab_123")
    assert artifact == {
        "artifact_id": "$artifact-1",
        "task_id": "collab_123",
        "name": "delivery-report.pdf",
        "mxc_uri": "mxc://matrix.test/media-1",
        "media_type": "application/pdf",
        "size": 2048,
        "sha256": "a" * 64,
        "purpose": "result",
        "sender": "@worker:matrix.test",
        "origin_server_ts": 1786168800000,
        "verification_status": "metadata_only",
        "content_verified": False,
        "safe_to_execute": False,
    }
    marker_only = {**event, "content": {**event["content"], HUB_EVENT_KEY: None}}
    assert event_artifact(marker_only, "collab_123") is None
    invalid_uri = {**event, "content": {**event["content"], "url": "https://objects.test/file"}}
    assert event_artifact(invalid_uri, "collab_123") is None


def test_unconfigured_boundaries_are_distinguishable():
    controller = AgentTeamsControllerClient(None)
    matrix = MatrixClient(None, None)
    with pytest.raises(AgentTeamsError, match="agentteams_controller_not_configured"):
        controller.teams("user-1")
    with pytest.raises(AgentTeamsError, match="agentteams_matrix_not_configured"):
        matrix.whoami()
    controller.close()
    matrix.close()
