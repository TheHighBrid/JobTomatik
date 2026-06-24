from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
from app.models.notification import NotificationType


class NotificationOut(BaseModel):
    id: int
    user_id: int
    type: NotificationType
    title: str
    message: Optional[str]
    data: Optional[Dict[str, Any]]
    read: bool
    created_at: datetime

    class Config:
        from_attributes = True
