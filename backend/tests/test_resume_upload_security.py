from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile, status

from app.api.profile import MAX_RESUME_BYTES, _store_resume_upload


@pytest.mark.asyncio
async def test_resume_upload_streams_a_valid_pdf_to_disk(tmp_path):
    destination = tmp_path / "resume.pdf"
    upload = UploadFile(
        filename="resume.pdf",
        file=BytesIO(b"%PDF-1.7\nminimal test document\n%%EOF"),
    )

    await _store_resume_upload(upload, destination)

    assert destination.read_bytes().startswith(b"%PDF-")
    assert {path.name for path in tmp_path.iterdir()} == {"resume.pdf"}


@pytest.mark.asyncio
async def test_resume_upload_rejects_a_renamed_non_pdf(tmp_path):
    destination = tmp_path / "resume.pdf"
    upload = UploadFile(filename="resume.pdf", file=BytesIO(b"not actually a pdf"))

    with pytest.raises(HTTPException) as exc_info:
        await _store_resume_upload(upload, destination)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_resume_upload_rejects_files_larger_than_ten_megabytes(tmp_path):
    destination = tmp_path / "resume.pdf"
    upload = UploadFile(
        filename="resume.pdf",
        file=BytesIO(b"%PDF-" + b"x" * MAX_RESUME_BYTES),
    )

    with pytest.raises(HTTPException) as exc_info:
        await _store_resume_upload(upload, destination)

    assert exc_info.value.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    assert list(tmp_path.iterdir()) == []


def test_resume_storage_is_not_mounted_as_public_static_content():
    from app import main

    route_paths = {getattr(route, "path", None) for route in main.app.routes}

    assert "/uploads" not in route_paths
