import uuid as _uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
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
    tbl = ScoreTrajectory.__table__

    # Atomic upsert: avoids a race condition where two concurrent test submissions
    # for the same user/subject/week both SELECT "no row" and both try to INSERT,
    # causing a UniqueConstraint violation and a 500 error.
    stmt = pg_insert(ScoreTrajectory).values(
        id=_uuid.uuid4(),
        user_id=user_id,
        subject_id=subject_id,
        week_start=week_start,
        avg_score=new_score,
        attempt_count=1,
        created_at=datetime.now(timezone.utc),
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_score_traj_user_subject_week",
        set_={
            "avg_score": (tbl.c.avg_score * tbl.c.attempt_count + stmt.excluded.avg_score)
            / (tbl.c.attempt_count + 1),
            "attempt_count": tbl.c.attempt_count + 1,
        },
    )
    await db.execute(stmt)
