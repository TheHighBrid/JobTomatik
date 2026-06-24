import os
import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import get_current_user
from app.models.user import User
from app.schemas.user import UserOut, UserUpdate
from app.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/profile", tags=["profile"])


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


@router.post("/resume", response_model=UserOut)
async def upload_resume(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if file.content_type not in ("application/pdf",):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    upload_dir = settings.upload_dir
    os.makedirs(upload_dir, exist_ok=True)

    filename = f"resume_{current_user.id}.pdf"
    filepath = os.path.join(upload_dir, filename)

    async with aiofiles.open(filepath, "wb") as out:
        content = await file.read()
        await out.write(content)

    current_user.resume_path = filepath
    current_user.resume_filename = file.filename
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
