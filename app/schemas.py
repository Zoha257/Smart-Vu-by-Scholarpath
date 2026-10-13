"""
app/schemas.py — Pydantic request/response models for the Admin API.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CourseCreate(BaseModel):
    course_code: str = Field(..., max_length=32, examples=["CS101"])
    title: str = Field(..., max_length=255)
    description: str = ""


class CourseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None


class CourseOut(BaseModel):
    id: uuid.UUID
    course_code: str
    title: str
    description: str
    created_at: datetime

    class Config:
        from_attributes = True


class LectureCreate(BaseModel):
    course_id: uuid.UUID
    title: str = Field(..., max_length=255)
    lecture_number: int
    # Optional now: a URL-sourced lecture sets this; an upload-sourced one
    # leaves it null and instead calls POST /{lecture_id}/upload-video
    # after creation (see lectures_admin.py).
    source_url: str | None = Field(
        None, description="Preferred: VU OCW URL. Fallback: YouTube URL (Section 21.3). "
        "Leave empty if you will upload a local video file instead."
    )


class LectureOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    title: str
    lecture_number: int
    source_type: str
    source_url: str | None
    duration_seconds: int | None
    processing_status: str
    processing_error: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class LectureUploadOut(BaseModel):
    lecture_id: uuid.UUID
    source_type: str
    stored_filename: str
    size_bytes: int


class IngestionTriggerRequest(BaseModel):
    force: bool = Field(
        False, description="Override the Section 22.7 daily ingestion pacing cap."
    )


class IngestionStatusOut(BaseModel):
    lecture_id: uuid.UUID
    processing_status: str
    processing_error: str | None
