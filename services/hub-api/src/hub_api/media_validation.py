from __future__ import annotations

import hashlib
import io
import json
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile


class MediaValidationError(ValueError):
    def __init__(self, code: str, *, actual_sha256: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.actual_sha256 = actual_sha256


def _normalize_media_type(value: str | None) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


def _zip_media_type(content: bytes, filename: str, max_uncompressed_bytes: int) -> str:
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 1000:
                raise MediaValidationError("artifact_archive_too_many_entries")
            total_uncompressed = 0
            names: set[str] = set()
            for entry in entries:
                normalized = entry.filename.replace("\\", "/")
                path = PurePosixPath(normalized)
                if path.is_absolute() or ".." in path.parts:
                    raise MediaValidationError("artifact_archive_path_unsafe")
                if ((entry.external_attr >> 16) & 0o170000) == 0o120000:
                    raise MediaValidationError("artifact_archive_symlink_not_allowed")
                total_uncompressed += entry.file_size
                if total_uncompressed > max_uncompressed_bytes:
                    raise MediaValidationError("artifact_archive_expansion_too_large")
                names.add(normalized.lower())
    except BadZipFile as exc:
        raise MediaValidationError("artifact_archive_invalid") from exc

    suffix = PurePosixPath(filename).suffix.lower()
    if "word/document.xml" in names:
        return (
            "application/vnd.ms-word.document.macroenabled.12"
            if suffix == ".docm"
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    if "xl/workbook.xml" in names:
        return (
            "application/vnd.ms-excel.sheet.macroenabled.12"
            if suffix == ".xlsm"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    if "ppt/presentation.xml" in names:
        return (
            "application/vnd.ms-powerpoint.presentation.macroenabled.12"
            if suffix == ".pptm"
            else "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
    return "application/zip"


def detect_media_type(content: bytes, filename: str, max_uncompressed_bytes: int) -> str:
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if content.startswith(b"PK\x03\x04"):
        return _zip_media_type(content, filename, max_uncompressed_bytes)

    suffix = PurePosixPath(filename).suffix.lower()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return "application/octet-stream"
    if suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise MediaValidationError("artifact_json_invalid") from exc
        return "application/json"
    if suffix == ".csv":
        return "text/csv"
    if suffix in {".md", ".markdown"}:
        return "text/markdown"
    return "text/plain"


def verify_media(
    *,
    content: bytes,
    filename: str,
    declared_media_type: str,
    response_media_type: str,
    claimed_size: int | None,
    claimed_sha256: str,
    max_uncompressed_bytes: int,
) -> dict[str, str | int]:
    actual_size = len(content)
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if len(claimed_sha256) != 64 or any(char not in "0123456789abcdefABCDEF" for char in claimed_sha256):
        raise MediaValidationError("artifact_sha256_invalid", actual_sha256=actual_sha256)
    if actual_sha256.lower() != claimed_sha256.lower():
        raise MediaValidationError("artifact_sha256_mismatch", actual_sha256=actual_sha256)
    if claimed_size is not None and actual_size != claimed_size:
        raise MediaValidationError("artifact_size_mismatch", actual_sha256=actual_sha256)

    detected_media_type = detect_media_type(content, filename, max_uncompressed_bytes)
    declared = _normalize_media_type(declared_media_type) or "application/octet-stream"
    response = _normalize_media_type(response_media_type) or "application/octet-stream"
    if detected_media_type == "application/octet-stream":
        raise MediaValidationError("artifact_media_type_unrecognized", actual_sha256=actual_sha256)
    if declared != "application/octet-stream" and declared != detected_media_type:
        raise MediaValidationError("artifact_declared_media_type_mismatch", actual_sha256=actual_sha256)
    if response != "application/octet-stream" and response != detected_media_type:
        raise MediaValidationError("artifact_response_media_type_mismatch", actual_sha256=actual_sha256)
    return {
        "actual_sha256": actual_sha256,
        "actual_size": actual_size,
        "detected_media_type": detected_media_type,
    }
