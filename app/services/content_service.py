import asyncio
import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Chapter, Lesson, Note, Subject
from app.models.progress import Test, TestAttempt, WatchHistory
from app.models.subscription import Plan
from app.models.user import User
from app.schemas.content import (
    ChapterDetailResponse,
    ChapterSummary,
    ClassSummary,
    LessonPlayResponse,
    LessonSummary,
    LessonTestAttemptSummary,
    LessonTestSummary,
    NotesResponse,
    SubjectDetailResponse,
    SubjectListItem,
)
from app.services.storage_service import generate_presigned_url
from app.utils.access_control import user_has_access


class AccessDenied(Exception):
    """Raised when a user attempts to access premium content without a valid subscription."""

    def __init__(self, subject_id: uuid.UUID, class_number: int) -> None:
        self.subject_id = subject_id
        self.class_number = class_number


async def get_classes(db: AsyncSession) -> list[ClassSummary]:
    """Return all active classes with their subject counts."""
    result = await db.execute(
        select(Subject.class_number, func.count(Subject.id).label("cnt"))
        .where(Subject.is_active.is_(True))
        .group_by(Subject.class_number)
        .order_by(Subject.class_number.desc())
    )
    labels = {10: "Class 10 (SSLC)", 9: "Class 9", 8: "Class 8", 7: "Class 7"}
    return [
        ClassSummary(
            class_number=row.class_number,
            label=labels.get(row.class_number, f"Class {row.class_number}"),
            subject_count=row.cnt,
        )
        for row in result.all()
    ]


async def get_subjects_by_class(
    db: AsyncSession,
    class_number: int,
    user: User | None,
) -> list[SubjectListItem]:
    """Return all active subjects for a class, with access and progress info for the user."""
    subjects_result = await db.execute(
        select(Subject)
        .where(Subject.class_number == class_number, Subject.is_active.is_(True))
        .order_by(Subject.order_index)
    )
    subjects = subjects_result.scalars().all()
    if not subjects:
        return []

    subject_ids = [s.id for s in subjects]
    chapter_counts_result = await db.execute(
        select(Chapter.subject_id, func.count(Chapter.id).label("cnt"))
        .where(Chapter.subject_id.in_(subject_ids), Chapter.is_published.is_(True))
        .group_by(Chapter.subject_id)
    )
    chapter_counts: dict[uuid.UUID, int] = {
        row.subject_id: row.cnt for row in chapter_counts_result.all()
    }

    items: list[SubjectListItem] = []
    for subject in subjects:
        has_access = False
        watch_pct = 0
        if user:
            has_access = await user_has_access(db, user, subject.id, class_number)
            watch_pct = await _subject_watch_percentage(db, user.id, subject.id)

        items.append(
            SubjectListItem(
                id=subject.id,
                name=subject.name,
                name_ml=subject.name_ml,
                slug=subject.slug,
                icon=subject.icon,
                color=subject.color,
                chapter_count=chapter_counts.get(subject.id, 0),
                monthly_price_paise=subject.monthly_price_paise,
                has_access=has_access,
                watch_percentage=watch_pct,
            )
        )
    return items


async def get_subject_detail(
    db: AsyncSession,
    subject_id: uuid.UUID,
    user: User,
) -> SubjectDetailResponse | None:
    """Return full subject detail including chapters, access status, and watch progress."""
    subject_result = await db.execute(
        select(Subject).where(Subject.id == subject_id, Subject.is_active.is_(True))
    )
    subject = subject_result.scalar_one_or_none()
    if subject is None:
        return None

    chapters_result = await db.execute(
        select(Chapter)
        .where(Chapter.subject_id == subject_id, Chapter.is_published.is_(True))
        .order_by(Chapter.order_index)
    )
    chapters = chapters_result.scalars().all()

    has_access, watch_pct, chapter_summaries = await asyncio.gather(
        user_has_access(db, user, subject.id, subject.class_number),
        _subject_watch_percentage(db, user.id, subject.id),
        asyncio.gather(*[_chapter_summary(db, ch, user.id) for ch in chapters]),
    )

    return SubjectDetailResponse(
        id=subject.id,
        name=subject.name,
        name_ml=subject.name_ml,
        slug=subject.slug,
        icon=subject.icon,
        color=subject.color,
        chapter_count=len(chapters),
        monthly_price_paise=subject.monthly_price_paise,
        has_access=has_access,
        watch_percentage=watch_pct,
        chapters=list(chapter_summaries),
    )


async def get_chapter_detail(
    db: AsyncSession,
    chapter_id: uuid.UUID,
    user: User,
) -> ChapterDetailResponse | None:
    """Return chapter detail with lesson list and per-lesson watch progress."""
    chapter_result = await db.execute(
        select(Chapter, Subject)
        .join(Subject, Chapter.subject_id == Subject.id)
        .where(
            Chapter.id == chapter_id,
            Chapter.is_published.is_(True),
            Subject.is_active.is_(True),
        )
    )
    row = chapter_result.first()
    if row is None:
        return None
    chapter, subject = row

    lessons_result = await db.execute(
        select(Lesson)
        .where(Lesson.chapter_id == chapter_id, Lesson.is_published.is_(True))
        .order_by(Lesson.order_index)
    )
    lessons = lessons_result.scalars().all()
    lesson_ids = [lesson.id for lesson in lessons]

    watch_map: dict[uuid.UUID, WatchHistory] = {}
    if lesson_ids:
        wh_result = await db.execute(
            select(WatchHistory).where(
                WatchHistory.user_id == user.id,
                WatchHistory.lesson_id.in_(lesson_ids),
            )
        )
        for wh in wh_result.scalars().all():
            watch_map[wh.lesson_id] = wh

    tests_by_lesson: dict[uuid.UUID, Test] = {}
    attempts_by_test: dict[uuid.UUID, TestAttempt] = {}
    if lesson_ids:
        tests_result = await db.execute(
            select(Test)
            .where(
                Test.lesson_id.in_(lesson_ids),
                Test.is_published.is_(True),
            )
            .order_by(Test.created_at, Test.id)
        )
        for test in tests_result.scalars().all():
            if test.lesson_id is not None and test.lesson_id not in tests_by_lesson:
                tests_by_lesson[test.lesson_id] = test

        if tests_by_lesson:
            attempts_result = await db.execute(
                select(TestAttempt)
                .where(
                    TestAttempt.user_id == user.id,
                    TestAttempt.test_id.in_([test.id for test in tests_by_lesson.values()]),
                )
                .order_by(TestAttempt.completed_at.desc())
            )
            for attempt in attempts_result.scalars().all():
                if attempt.test_id not in attempts_by_test:
                    attempts_by_test[attempt.test_id] = attempt

    has_access = await user_has_access(db, user, subject.id, subject.class_number)

    lesson_summaries: list[LessonSummary] = []
    for lesson in lessons:
        watch = watch_map.get(lesson.id)
        test = tests_by_lesson.get(lesson.id)
        test_summary: LessonTestSummary | None = None
        if test is not None:
            is_lesson_completed = watch.is_completed if watch else False
            is_unlocked = is_lesson_completed and (lesson.is_free or has_access)
            unlock_reason = None
            if not lesson.is_free and not has_access:
                unlock_reason = "subscription_required"
            elif not is_lesson_completed:
                unlock_reason = "complete_lesson"

            last_attempt = attempts_by_test.get(test.id)
            test_summary = LessonTestSummary(
                id=test.id,
                title=test.title,
                duration_minutes=test.duration_minutes,
                total_marks=test.total_marks,
                question_count=len(test.questions),
                is_unlocked=is_unlocked,
                unlock_reason=unlock_reason,
                last_attempt=LessonTestAttemptSummary(
                    score=last_attempt.score,
                    total_marks=last_attempt.total_marks,
                    percentage=float(last_attempt.percentage or 0),
                    completed_at=last_attempt.completed_at,
                )
                if last_attempt
                else None,
            )

        lesson_summaries.append(
            LessonSummary(
                id=lesson.id,
                title=lesson.title,
                duration_seconds=lesson.duration_seconds,
                is_free=lesson.is_free,
                is_locked=not lesson.is_free and not has_access,
                thumbnail_url=lesson.thumbnail_url,
                watch_percentage=watch.watch_percentage if watch else 0,
                is_completed=watch.is_completed if watch else False,
                test=test_summary,
            )
        )

    has_notes_result = await db.execute(
        select(func.count(Note.id)).where(Note.chapter_id == chapter_id)
    )
    has_notes = (has_notes_result.scalar() or 0) > 0

    test_result = await db.execute(
        select(Test.id).where(
            Test.chapter_id == chapter_id,
            Test.lesson_id.isnot(None),
            Test.is_published.is_(True),
        ).limit(1)
    )
    test_id = test_result.scalar_one_or_none()

    return ChapterDetailResponse(
        id=chapter.id,
        subject_id=subject.id,
        title=chapter.title,
        lessons=lesson_summaries,
        has_notes=has_notes,
        test_id=test_id,
    )


async def get_lesson_play(
    db: AsyncSession,
    lesson_id: uuid.UUID,
    user: User,
) -> LessonPlayResponse | None:
    """Return the playback data for a lesson, enforcing access control on premium content."""
    result = await db.execute(
        select(Lesson, Chapter, Subject)
        .join(Chapter, Lesson.chapter_id == Chapter.id)
        .join(Subject, Chapter.subject_id == Subject.id)
        .where(Lesson.id == lesson_id, Lesson.is_published.is_(True))
    )
    row = result.first()
    if row is None:
        return None

    lesson, chapter, subject = row

    if not lesson.is_free:
        has_access = await user_has_access(db, user, subject.id, subject.class_number)
        if not has_access:
            raise AccessDenied(subject.id, subject.class_number)

    wh_result = await db.execute(
        select(WatchHistory).where(
            WatchHistory.user_id == user.id,
            WatchHistory.lesson_id == lesson_id,
        )
    )
    wh = wh_result.scalar_one_or_none()
    watch_pct = wh.watch_percentage if wh else 0
    resume_at = wh.current_time_seconds if wh else 0

    return LessonPlayResponse(
        youtube_video_id=lesson.youtube_video_id,
        title=lesson.title,
        duration_seconds=lesson.duration_seconds,
        watch_percentage=watch_pct,
        resume_at_seconds=resume_at,
    )


async def get_chapter_notes(
    db: AsyncSession,
    chapter_id: uuid.UUID,
    user: User,
) -> NotesResponse | None:
    """Return a presigned download URL for chapter notes, enforcing access control."""
    result = await db.execute(
        select(Chapter, Subject)
        .join(Subject, Chapter.subject_id == Subject.id)
        .where(Chapter.id == chapter_id, Chapter.is_published.is_(True))
    )
    row = result.first()
    if row is None:
        return None
    chapter, subject = row

    note_result = await db.execute(
        select(Note).where(Note.chapter_id == chapter_id).limit(1)
    )
    note = note_result.scalar_one_or_none()
    if note is None:
        return None

    if note.is_premium:
        has_access = await user_has_access(db, user, subject.id, subject.class_number)
        if not has_access:
            raise AccessDenied(subject.id, subject.class_number)

    url = await generate_presigned_url(note.r2_key, expires_in=3600)
    return NotesResponse(
        url=url,
        expires_in_seconds=3600,
        title=note.title,
        file_size_bytes=note.file_size_bytes,
    )


async def get_relevant_plan_slugs(
    db: AsyncSession,
    subject_id: uuid.UUID,
    class_number: int,
) -> list[str]:
    """Return up to 3 plan slugs that would grant access to the given subject."""
    result = await db.execute(
        select(Plan.slug)
        .where(
            Plan.is_active.is_(True),
            or_(
                Plan.plan_type == "full_access",
                and_(
                    Plan.plan_type.in_(["complete", "seasonal"]),
                    Plan.class_numbers.contains([class_number]),
                ),
                and_(
                    Plan.plan_type.in_(["bundle", "single_subject", "lifetime"]),
                    Plan.subject_ids.contains([subject_id]),
                ),
            ),
        )
        .order_by(Plan.order_index)
        .limit(3)
    )
    return [row[0] for row in result.all()]


# ── helpers ───────────────────────────────────────────────────────────────────

async def _subject_watch_percentage(
    db: AsyncSession, user_id: uuid.UUID, subject_id: uuid.UUID
) -> int:
    """Return the average watch percentage across all published lessons in a subject."""
    lesson_ids_result = await db.execute(
        select(Lesson.id)
        .join(Chapter, Lesson.chapter_id == Chapter.id)
        .where(Chapter.subject_id == subject_id, Lesson.is_published.is_(True))
    )
    lesson_ids = [row[0] for row in lesson_ids_result.all()]
    if not lesson_ids:
        return 0

    total_result = await db.execute(
        select(func.coalesce(func.sum(WatchHistory.watch_percentage), 0)).where(
            WatchHistory.user_id == user_id,
            WatchHistory.lesson_id.in_(lesson_ids),
        )
    )
    return round(float(total_result.scalar() or 0) / len(lesson_ids))


async def _chapter_summary(
    db: AsyncSession, chapter: Chapter, user_id: uuid.UUID
) -> ChapterSummary:
    """Build a ChapterSummary including lesson count, test presence, and watch progress."""
    lesson_ids_result = await db.execute(
        select(Lesson.id).where(
            Lesson.chapter_id == chapter.id, Lesson.is_published.is_(True)
        )
    )
    lesson_ids = [row[0] for row in lesson_ids_result.all()]
    lesson_count = len(lesson_ids)

    test_result = await db.execute(
        select(Test.id).where(
            Test.chapter_id == chapter.id,
            Test.lesson_id.isnot(None),
            Test.is_published.is_(True),
        ).limit(1)
    )
    has_test = test_result.scalar_one_or_none() is not None

    watch_pct = 0
    is_completed = False
    if lesson_ids:
        total_result = await db.execute(
            select(func.coalesce(func.sum(WatchHistory.watch_percentage), 0)).where(
                WatchHistory.user_id == user_id,
                WatchHistory.lesson_id.in_(lesson_ids),
            )
        )
        watch_pct = round(float(total_result.scalar() or 0) / lesson_count)

        completed_result = await db.execute(
            select(func.count(WatchHistory.id)).where(
                WatchHistory.user_id == user_id,
                WatchHistory.lesson_id.in_(lesson_ids),
                WatchHistory.is_completed.is_(True),
            )
        )
        completed_count = completed_result.scalar() or 0
        is_completed = lesson_count > 0 and completed_count == lesson_count

    return ChapterSummary(
        id=chapter.id,
        chapter_number=chapter.chapter_number,
        title=chapter.title,
        title_ml=chapter.title_ml,
        lesson_count=lesson_count,
        has_test=has_test,
        watch_percentage=watch_pct,
        is_completed=is_completed,
    )
