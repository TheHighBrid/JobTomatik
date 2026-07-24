import os
from pathlib import Path
from uuid import uuid4

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserOut, UserUpdate


settings = get_settings()
router = APIRouter(prefix="/profile", tags=["profile"])

MAX_RESUME_BYTES = 10 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
PDF_SIGNATURE = b"%PDF-"


@router.get("", response_model=UserOut)
async def get_profile(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("", response_model=UserOut)
async def update_profile(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


async def _store_resume_upload(file: UploadFile, destination: Path) -> None:
    """Store a bounded PDF upload without loading the whole résumé into memory."""
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.upload")
    total_bytes = 0
    signature = b""

    try:
        async with aiofiles.open(temporary, "wb") as out:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                if len(signature) < len(PDF_SIGNATURE):
                    needed = len(PDF_SIGNATURE) - len(signature)
                    signature += chunk[:needed]
                total_bytes += len(chunk)
                if total_bytes > MAX_RESUME_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Resume PDF must be 10 MB or smaller",
                    )
                await out.write(chunk)

        if total_bytes == 0 or signature != PDF_SIGNATURE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The uploaded file is not a valid PDF",
            )

        os.replace(temporary, destination)
    finally:
        await file.close()
        if temporary.exists():
            temporary.unlink(missing_ok=True)


@router.post("/resume", response_model=UserOut)
async def upload_resume(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Android and iOS MIME types are unreliable, so validate the extension and
    # the file signature instead of trusting Content-Type alone.
    display_filename = os.path.basename((file.filename or "").replace("\\", "/"))[:255]
    if not display_filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please upload a PDF file (.pdf extension required)",
        )

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    filepath = upload_dir / f"resume_{current_user.id}.pdf"

    await _store_resume_upload(file, filepath)

    current_user.resume_path = str(filepath)
    current_user.resume_filename = display_filename
    db.commit()
    db.refresh(current_user)
    return current_user


@router.delete("/resume", response_model=UserOut)
async def delete_resume(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.resume_path and os.path.exists(current_user.resume_path):
        os.remove(current_user.resume_path)
    current_user.resume_path = None
    current_user.resume_filename = None
    db.commit()
    db.refresh(current_user)
    return current_user
