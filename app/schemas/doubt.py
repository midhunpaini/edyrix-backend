from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DoubtCreateRequest(BaseModel):
    lesson_id: UUID | None = None
    chapter_id: UUID | None = None
    question_text: str


class DoubtCreateResponse(BaseModel):
    id: UUID
    status: str


class DoubtListItem(BaseModel):
    id: UUID
    question_text: str
    status: str
    answer_text: str | None
    created_at: datetime
    answered_at: datetime | None


class AnswerDoubtRequest(BaseModel):
    answer_text: str


class AnswerDoubtResponse(BaseModel):
    message: str
    notification_sent: bool
