# schemas.py
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import uuid

class ImageRecord(BaseModel):
    id: str
    user_id: str
    r2_url: str
    object_name: str
    uploaded_at: datetime

    model_config = {
      "from_attributes": True
    }

class BulkDeleteRequest(BaseModel):
    image_ids: List[str] = Field(..., min_length=1)

class UploadResponse(BaseModel):
    success: bool
    image_id: Optional[str] = None
    filename: str
    detail: Optional[str] = None

class BulkUploadResponse(BaseModel):
    results: List[UploadResponse]