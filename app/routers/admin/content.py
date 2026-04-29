import uuid

from fastapi import APIRouter, Depends, Query, Request, UploadFile, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_admin
from app.exceptions import BadRequestException, ConflictException, NotFoundException
from app.models.admin import AdminUser
from app.models.content import Chapter, Lesson, Note, Subject
from app.schemas.admin import (
    BulkCreateLessonsRequest,
    BulkCreateLessonsResponse,
    ChapterAdminResponse,
    CreateChapterRequest,
    CreateSubjectRequest,
    NoteAdminItem,
    NoteUploadResponse,
    PublishToggleResponse,
    ReorderRequest,
    SubjectAdminResponse,
    SubjectChaptersAdminResponse,
)
from app.schemas.common import CommonResponse
from app.schemas.content import CreateLessonRequest, LessonResponse, UpdateLessonRequest
from app.services.storage_service import delete_object, generate_presigned_url, upload_bytes
from app.utils.audit import log_audit

router = APIRouter(tags=["admin:content"])

_ALLOWED_CONTENT_TYPES = {"application/pdf"}
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


@router.post("/subjects", response_model=CommonResponse[SubjectAdminResponse], status_code=status.HTTP_201_CREATED)
async def create_subject(
    body: CreateSubjectRequest,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[SubjectAdminResponse]:
    existing = await db.execute(select(Subject).where(Subject.slug == body.slug))
    if existing.scalar_one_or_none():
        raise ConflictException("Slug already exists")
    subject = Subject(
        name=body.name, name_ml=body.name_ml, slug=body.slug,
        class_number=body.class_number, icon=body.icon, color=body.color,
        monthly_price_paise=body.monthly_price_paise, order_index=body.order_index,
    )
    db.add(subject)
    await db.commit()
    await db.refresh(subject)
    return CommonResponse.ok(SubjectAdminResponse.model_validate(subject), "Subject created")


@router.get("/subjects/{subject_id}", response_model=CommonResponse[SubjectChaptersAdminResponse])
async def get_subject_with_chapters(
    subject_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[SubjectChaptersAdminResponse]:
    subject = (await db.execute(select(Subject).where(Subject.id == subject_id))).scalar_one_or_none()
    if subject is None:
        raise NotFoundException("Subject not found")
    chapters = (
        await db.execute(select(Chapter).where(Chapter.subject_id == subject_id).order_by(Chapter.order_index))
    ).scalars().all()
    return CommonResponse.ok(SubjectChaptersAdminResponse(
        id=subject.id, name=subject.name,
        chapters=[ChapterAdminResponse.model_validate(ch) for ch in chapters],
    ))


@router.post("/chapters", response_model=CommonResponse[ChapterAdminResponse], status_code=status.HTTP_201_CREATED)
async def create_chapter(
    body: CreateChapterRequest,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[ChapterAdminResponse]:
    if (await db.execute(select(Subject).where(Subject.id == body.subject_id, Subject.is_active.is_(True)))).scalar_one_or_none() is None:
        raise NotFoundException("Subject not found")
    chapter = Chapter(
        subject_id=body.subject_id, chapter_number=body.chapter_number,
        title=body.title, title_ml=body.title_ml,
        description=body.description, order_index=body.order_index,
    )
    db.add(chapter)
    await db.commit()
    await db.refresh(chapter)
    return CommonResponse.ok(ChapterAdminResponse.model_validate(chapter), "Chapter created")


@router.get("/chapters/{chapter_id}/lessons", response_model=CommonResponse[list[LessonResponse]])
async def list_chapter_lessons(
    chapter_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[list[LessonResponse]]:
    if (await db.execute(select(Chapter).where(Chapter.id == chapter_id))).scalar_one_or_none() is None:
        raise NotFoundException("Chapter not found")
    lessons = (
        await db.execute(select(Lesson).where(Lesson.chapter_id == chapter_id).order_by(Lesson.order_index))
    ).scalars().all()
    return CommonResponse.ok([LessonResponse.model_validate(lesson) for lesson in lessons])


@router.patch("/chapters/{chapter_id}/publish", response_model=CommonResponse[PublishToggleResponse])
async def toggle_chapter_publish(
    chapter_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[PublishToggleResponse]:
    chapter = (await db.execute(select(Chapter).where(Chapter.id == chapter_id))).scalar_one_or_none()
    if chapter is None:
        raise NotFoundException("Chapter not found")
    chapter.is_published = not chapter.is_published
    await db.commit()
    return CommonResponse.ok(PublishToggleResponse(id=chapter.id, is_published=chapter.is_published))


@router.put("/chapters/reorder", response_model=CommonResponse[dict])
async def reorder_chapters(
    body: ReorderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> CommonResponse[dict]:
    for item in body.items:
        await db.execute(update(Chapter).where(Chapter.id == item.id).values(order_index=item.order_index))
    await log_audit(db, admin.id, "chapter.reorder", "chapter", None, {}, request)
    await db.commit()
    return CommonResponse.ok({"reordered": len(body.items)})


@router.post("/lessons/bulk", response_model=CommonResponse[BulkCreateLessonsResponse], status_code=status.HTTP_201_CREATED)
async def bulk_create_lessons(
    body: BulkCreateLessonsRequest,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[BulkCreateLessonsResponse]:
    if (await db.execute(select(Chapter).where(Chapter.id == body.chapter_id))).scalar_one_or_none() is None:
        raise NotFoundException("Chapter not found")
    created = 0
    errors: list[str] = []
    for i, item in enumerate(body.lessons, start=1):
        try:
            lesson = Lesson(
                chapter_id=body.chapter_id, title=item.title, title_ml=item.title_ml,
                youtube_video_id=item.youtube_video_id, duration_seconds=item.duration_seconds,
                is_free=item.is_free, order_index=item.order_index,
            )
            db.add(lesson)
            created += 1
        except Exception as exc:
            errors.append(f"Row {i} ({item.title!r}): {exc}")
    await db.commit()
    return CommonResponse.ok(BulkCreateLessonsResponse(created=created, errors=errors), f"{created} lesson(s) created")


@router.put("/lessons/reorder", response_model=CommonResponse[dict])
async def reorder_lessons(
    body: ReorderRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> CommonResponse[dict]:
    for item in body.items:
        await db.execute(update(Lesson).where(Lesson.id == item.id).values(order_index=item.order_index))
    await log_audit(db, admin.id, "lesson.reorder", "lesson", None, {}, request)
    await db.commit()
    return CommonResponse.ok({"reordered": len(body.items)})


@router.post("/lessons", response_model=CommonResponse[LessonResponse], status_code=status.HTTP_201_CREATED)
async def create_lesson(
    body: CreateLessonRequest,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[LessonResponse]:
    if (await db.execute(select(Chapter).where(Chapter.id == body.chapter_id))).scalar_one_or_none() is None:
        raise NotFoundException("Chapter not found")
    lesson = Lesson(
        chapter_id=body.chapter_id, title=body.title, title_ml=body.title_ml,
        youtube_video_id=body.youtube_video_id, duration_seconds=body.duration_seconds,
        is_free=body.is_free, order_index=body.order_index,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return CommonResponse.ok(LessonResponse.model_validate(lesson), "Lesson created")


@router.put("/lessons/{lesson_id}", response_model=CommonResponse[LessonResponse])
async def update_lesson(
    lesson_id: uuid.UUID,
    body: UpdateLessonRequest,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[LessonResponse]:
    lesson = (await db.execute(select(Lesson).where(Lesson.id == lesson_id))).scalar_one_or_none()
    if lesson is None:
        raise NotFoundException("Lesson not found")
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(lesson, field, val)
    await db.commit()
    await db.refresh(lesson)
    return CommonResponse.ok(LessonResponse.model_validate(lesson))


@router.delete("/lessons/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> None:
    lesson = (await db.execute(select(Lesson).where(Lesson.id == lesson_id))).scalar_one_or_none()
    if lesson is None:
        raise NotFoundException("Lesson not found")
    await db.delete(lesson)
    await db.commit()


@router.patch("/lessons/{lesson_id}/publish", response_model=CommonResponse[PublishToggleResponse])
async def toggle_lesson_publish(
    lesson_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[PublishToggleResponse]:
    lesson = (await db.execute(select(Lesson).where(Lesson.id == lesson_id))).scalar_one_or_none()
    if lesson is None:
        raise NotFoundException("Lesson not found")
    lesson.is_published = not lesson.is_published
    await db.commit()
    return CommonResponse.ok(PublishToggleResponse(id=lesson.id, is_published=lesson.is_published))


@router.post("/notes/upload", response_model=CommonResponse[NoteUploadResponse], status_code=status.HTTP_201_CREATED)
async def upload_note(
    chapter_id: uuid.UUID = Query(...),
    title: str = Query(...),
    file: UploadFile = ...,
    is_premium: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[NoteUploadResponse]:
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise BadRequestException("Only PDF files are allowed")
    if (await db.execute(select(Chapter).where(Chapter.id == chapter_id))).scalar_one_or_none() is None:
        raise NotFoundException("Chapter not found")
    pdf_bytes = await file.read()
    if len(pdf_bytes) > _MAX_UPLOAD_BYTES:
        raise BadRequestException("File exceeds 20 MB limit")
    r2_key = f"notes/{uuid.uuid4()}.pdf"
    await upload_bytes(pdf_bytes, r2_key, content_type="application/pdf")
    note = Note(chapter_id=chapter_id, title=title, r2_key=r2_key, file_size_bytes=len(pdf_bytes), is_premium=is_premium)
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return CommonResponse.ok(NoteUploadResponse(id=note.id, r2_key=note.r2_key, file_size_bytes=note.file_size_bytes), "Notes uploaded")


@router.get("/notes/{chapter_id}", response_model=CommonResponse[list[NoteAdminItem]])
async def list_chapter_notes(
    chapter_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: AdminUser = Depends(require_admin),
) -> CommonResponse[list[NoteAdminItem]]:
    if (await db.execute(select(Chapter).where(Chapter.id == chapter_id))).scalar_one_or_none() is None:
        raise NotFoundException("Chapter not found")
    notes_result = await db.execute(select(Note).where(Note.chapter_id == chapter_id).order_by(Note.created_at))
    notes = notes_result.scalars().all()
    items = []
    for note in notes:
        url = await generate_presigned_url(note.r2_key, expires_in=3600)
        items.append(NoteAdminItem(
            id=note.id, title=note.title, r2_key=note.r2_key,
            file_size_bytes=note.file_size_bytes, presigned_url=url, created_at=note.created_at,
        ))
    return CommonResponse.ok(items)


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminUser = Depends(require_admin),
) -> None:
    note = (await db.execute(select(Note).where(Note.id == note_id))).scalar_one_or_none()
    if note is None:
        raise NotFoundException("Note not found")
    r2_key = note.r2_key
    await db.delete(note)
    await log_audit(db, admin.id, "note.delete", "note", note_id, {"r2_key": r2_key}, request)
    await db.commit()
    await delete_object(r2_key)
