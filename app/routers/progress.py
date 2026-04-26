from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.exceptions import BadRequestException, NotFoundException
from app.models.content import Chapter, Lesson, Subject
from app.models.progress import WatchHistory
from app.models.user import User
from app.schemas.common import CommonResponse
from app.schemas.progress import (
    ChapterProgressResponse,
    LessonProgress,
    ProgressSummaryResponse,
    SubjectProgress,
    WatchHeartbeatRequest,
    WatchHeartbeatResponse,
)

router = APIRouter(prefix="/progress", tags=["progress"])


@router.post("/watch", response_model=CommonResponse[WatchHeartbeatResponse])
async def watch_heartbeat(
    body: WatchHeartbeatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[WatchHeartbeatResponse]:
    if not (0 <= body.percentage <= 100):
        raise BadRequestException("percentage must be 0–100")

    lesson_exists = await db.execute(
        select(Lesson.id).where(Lesson.id == body.lesson_id, Lesson.is_published.is_(True))
    )
    if lesson_exists.scalar_one_or_none() is None:
        raise NotFoundException("Lesson not found")

    now = datetime.now(timezone.utc)
    is_completed = body.percentage >= 80

    result = await db.execute(
        select(WatchHistory).where(
            WatchHistory.user_id == user.id,
            WatchHistory.lesson_id == body.lesson_id,
        )
    )
    wh = result.scalar_one_or_none()
    if wh:
        wh.watch_percentage = max(wh.watch_percentage, body.percentage)
        wh.is_completed = wh.is_completed or is_completed
        wh.last_watched_at = now
    else:
        wh = WatchHistory(
            user_id=user.id,
            lesson_id=body.lesson_id,
            watch_percentage=body.percentage,
            is_completed=is_completed,
            last_watched_at=now,
        )
        db.add(wh)

    await db.commit()
    return CommonResponse.ok(WatchHeartbeatResponse(is_completed=wh.is_completed))


@router.get("/summary", response_model=CommonResponse[ProgressSummaryResponse])
async def get_progress_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[ProgressSummaryResponse]:
    subjects_result = await db.execute(
        select(Subject)
        .join(Chapter, Chapter.subject_id == Subject.id)
        .join(Lesson, Lesson.chapter_id == Chapter.id)
        .join(WatchHistory, WatchHistory.lesson_id == Lesson.id)
        .where(WatchHistory.user_id == user.id, Subject.is_active.is_(True))
        .distinct()
    )
    subjects = subjects_result.scalars().all()

    subject_progresses: list[SubjectProgress] = []
    overall_pcts: list[int] = []

    for subject in subjects:
        chapters_result = await db.execute(
            select(Chapter.id).where(
                Chapter.subject_id == subject.id, Chapter.is_published.is_(True)
            )
        )
        chapter_ids = [row[0] for row in chapters_result.all()]
        chapters_total = len(chapter_ids)

        chapters_completed = 0
        for ch_id in chapter_ids:
            lesson_ids_r = await db.execute(
                select(Lesson.id).where(
                    Lesson.chapter_id == ch_id, Lesson.is_published.is_(True)
                )
            )
            lesson_ids = [r[0] for r in lesson_ids_r.all()]
            if not lesson_ids:
                continue
            completed_r = await db.execute(
                select(func.count(WatchHistory.id)).where(
                    WatchHistory.user_id == user.id,
                    WatchHistory.lesson_id.in_(lesson_ids),
                    WatchHistory.is_completed.is_(True),
                )
            )
            if (completed_r.scalar() or 0) == len(lesson_ids):
                chapters_completed += 1

        pct = round(chapters_completed * 100 / chapters_total) if chapters_total else 0
        overall_pcts.append(pct)
        subject_progresses.append(
            SubjectProgress(
                subject_id=subject.id,
                name=subject.name,
                chapters_completed=chapters_completed,
                chapters_total=chapters_total,
                percentage=pct,
            )
        )

    overall = round(sum(overall_pcts) / len(overall_pcts)) if overall_pcts else 0
    return CommonResponse.ok(ProgressSummaryResponse(overall_percentage=overall, subjects=subject_progresses))


@router.get("/chapter/{chapter_id}", response_model=CommonResponse[ChapterProgressResponse])
async def get_chapter_progress(
    chapter_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommonResponse[ChapterProgressResponse]:
    chapter_result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id, Chapter.is_published.is_(True))
    )
    if chapter_result.scalar_one_or_none() is None:
        raise NotFoundException("Chapter not found")

    lessons_result = await db.execute(
        select(Lesson).where(Lesson.chapter_id == chapter_id, Lesson.is_published.is_(True))
    )
    lessons = lessons_result.scalars().all()
    lesson_ids = [l.id for l in lessons]

    wh_result = await db.execute(
        select(WatchHistory).where(
            WatchHistory.user_id == user.id,
            WatchHistory.lesson_id.in_(lesson_ids),
        )
    )
    watch_map = {wh.lesson_id: wh for wh in wh_result.scalars().all()}

    lessons_completed = sum(1 for lid in lesson_ids if watch_map.get(lid) and watch_map[lid].is_completed)
    lessons_total = len(lesson_ids)
    percentage = round(lessons_completed * 100 / lessons_total) if lessons_total else 0

    return CommonResponse.ok(ChapterProgressResponse(
        chapter_id=chapter_id,
        lessons_completed=lessons_completed,
        lessons_total=lessons_total,
        percentage=percentage,
        lessons=[
            LessonProgress(
                lesson_id=lid,
                watch_percentage=watch_map[lid].watch_percentage if lid in watch_map else 0,
                is_completed=watch_map[lid].is_completed if lid in watch_map else False,
            )
            for lid in lesson_ids
        ],
    ))
