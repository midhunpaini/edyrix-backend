from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.progress import ScoreTrajectory


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def update_trajectory(
    db: AsyncSession,
    user_id: UUID,
    subject_id: UUID,
    new_score: Decimal,
) -> None:
    today = date.today()
    week_start = _week_start(today)

    existing = await db.execute(
        select(ScoreTrajectory).where(
            ScoreTrajectory.user_id == user_id,
            ScoreTrajectory.subject_id == subject_id,
            ScoreTrajectory.week_start == week_start,
        )
    )
    row = existing.scalar_one_or_none()

    if row:
        count = row.attempt_count + 1
        row.avg_score = ((row.avg_score * row.attempt_count) + new_score) / count
        row.attempt_count = count
    else:
        db.add(
            ScoreTrajectory(
                user_id=user_id,
                subject_id=subject_id,
                week_start=week_start,
                avg_score=new_score,
                attempt_count=1,
            )
        )
