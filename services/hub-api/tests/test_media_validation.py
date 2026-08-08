from __future__ import annotations

import hashlib
import io
from zipfile import ZipFile

import pytest

from hub_api.media_validation import MediaValidationError, detect_media_type, verify_media


def test_pdf_size_mime_and_sha256_are_verified():
    content = b"%PDF-1.7\nverified\n"
    digest = hashlib.sha256(content).hexdigest()
    result = verify_media(
        content=content,
        filename="report.pdf",
        declared_media_type="application/pdf",
        response_media_type="application/pdf; charset=binary",
        claimed_size=len(content),
        claimed_sha256=digest,
        max_uncompressed_bytes=1024,
    )
    assert result == {
        "actual_sha256": digest,
        "actual_size": len(content),
        "detected_media_type": "application/pdf",
    }

    with pytest.raises(MediaValidationError, match="artifact_sha256_mismatch"):
        verify_media(
            content=content,
            filename="report.pdf",
            declared_media_type="application/pdf",
            response_media_type="application/pdf",
            claimed_size=len(content),
            claimed_sha256="0" * 64,
            max_uncompressed_bytes=1024,
        )


def test_zip_metadata_blocks_path_escape_and_detects_ooxml():
    valid_buffer = io.BytesIO()
    with ZipFile(valid_buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
    assert detect_media_type(valid_buffer.getvalue(), "report.docx", 4096) == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    unsafe_buffer = io.BytesIO()
    with ZipFile(unsafe_buffer, "w") as archive:
        archive.writestr("../escape.txt", "blocked")
    with pytest.raises(MediaValidationError, match="artifact_archive_path_unsafe"):
        detect_media_type(unsafe_buffer.getvalue(), "unsafe.zip", 4096)
