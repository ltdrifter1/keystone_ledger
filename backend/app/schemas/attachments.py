from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AttachmentOut(BaseModel):
    id: int
    entity_table: str
    entity_id: int
    filename: str
    content_type: str
    uploaded_by: str
    uploaded_at: datetime
    size_bytes: Optional[int] = None
