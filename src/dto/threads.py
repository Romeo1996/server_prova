from pydantic import BaseModel
from typing import Optional


class ThreadResponse(BaseModel):
    id: str
    title: Optional[str] = None
    updated_at: Optional[float] = None
    state: Optional[dict] = None


class ThreadListResponse(BaseModel):
    threads: list[ThreadResponse]


class ThreadUpdateRequest(BaseModel):
    title: Optional[str] = None
