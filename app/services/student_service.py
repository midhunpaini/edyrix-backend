import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundException
from app.models.content import Lesson, Subject
from app.models.progress import Test, TestAttempt, WatchHistory
from app.models.subscription import Payment, Plan, Subscription
from app.models.user import FreeTrial, User


async def list_students(
    db: AsyncSession,
    page: int,
    limit: int,
    search: str | None,
    class_number: int | None,
    subscription_status: Literal["active", "trial", "free"] | None,
) -> tuple[int, list[dict]]:
    now = datetime.now(timezone.utc)
    offset = (page - 1) * limit

    active_sub_sq = (
        select(Subscription.user_id)
        .where(
            Subscription.status == "active",
            or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
        )
        .distinct()
        .subquery()
    )
    active_trial_sq = (
        select(FreeTrial.user_id)
        .where(FreeTrial.expires_at > now)
        .where(~FreeTrial.user_id.in_(select(active_sub_sq.c.user_id)))
        .distinct()
        .subquery()
    )

    base = select(User).where(User.role == "student")
    if search:
        like = f"%{search}%"
        base = base.where(or_(User.name.ilike(like), User.phone.ilike(like), User.email.ilike(like)))
    if class_number:
        base = base.where(User.current_class == class_number)
    if subscription_status == "active":
        base = base.where(User.id.in_(select(active_sub_sq.c.user_id)))
    elif subscription_status == "trial":
        base = base.where(User.id.in_(select(active_trial_sq.c.user_id)))
    elif subscription_status == "free":
        base = base.where(
            ~User.id.in_(select(active_sub_sq.c.user_id)),
            ~User.id.in_(select(active_trial_sq.c.user_id)),
        )

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0
    users = (await db.execute(base.order_by(User.created_at.desc()).limit(limit).offset(offset))).scalars().all()

    if not users:
        return total, []

    user_ids = [u.id for u in users]
    active_sub_ids: set[uuid.UUID] = {
        row[0] for row in (
            await db.execute(
                select(Subscription.user_id).where(
                    Subscription.user_id.in_(user_ids),
                    Subscription.status == "active",
                    or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
                )
            )
        ).all()
    }
    active_trial_ids: set[uuid.UUID] = {
        row[0] for row in (
            await db.execute(
                select(FreeTrial.user_id).where(
                    FreeTrial.user_id.in_(user_ids), FreeTrial.expires_at > now
                )
            )
        ).all()
    }

    items = [
        {
            "id": user.id,
            "name": user.name,
            "phone": user.phone,
            "email": user.email,
            "current_class": user.current_class,
            "is_suspended": user.is_suspended,
            "subscription_status": (
                "active" if user.id in active_sub_ids
                else "trial" if user.id in active_trial_ids
                else "free"
            ),
            "joined_at": user.created_at,
        }
        for user in users
    ]
    return total, items


async def get_student_detail(db: AsyncSession, student_id: uuid.UUID) -> dict:
    now = datetime.now(timezone.utc)

    user = (
        await db.execute(select(User).where(User.id == student_id, User.role == "student"))
    ).scalar_one_or_none()
    if user is None:
        raise NotFoundException("Student not found")

    active_sub = (
        await db.execute(
            select(Subscription).where(
                Subscription.user_id == student_id,
                Subscription.status == "active",
                or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
            ).limit(1)
        )
    ).scalar_one_or_none()
    trial = (
        await db.execute(
            select(FreeTrial).where(FreeTrial.user_id == student_id, FreeTrial.expires_at > now)
        )
    ).scalar_one_or_none()
    sub_status = "active" if active_sub else ("trial" if trial else "free")

    videos_watched = (
        await db.execute(select(func.count(WatchHistory.id)).where(WatchHistory.user_id == student_id))
    ).scalar() or 0
    test_row = (
        await db.execute(
            select(func.count(TestAttempt.id), func.coalesce(func.avg(TestAttempt.percentage), 0))
            .where(TestAttempt.user_id == student_id)
        )
    ).one()
    tests_taken = test_row[0] or 0
    avg_score = round(float(test_row[1] or 0), 1)

    subject_progress_result = await db.execute(
        select(
            Subject.name,
            func.coalesce(func.avg(WatchHistory.watch_percentage), 0).label("pct"),
        )
        .join(Lesson, Lesson.subject_id == Subject.id)
        .join(WatchHistory, and_(WatchHistory.lesson_id == Lesson.id, WatchHistory.user_id == student_id))
        .group_by(Subject.name)
    )
    subject_progress = [
        {"subject": r[0], "pct": round(float(r[1]), 1)}
        for r in subject_progress_result.all()
    ]

    payments_result = await db.execute(
        select(Plan.name, Payment.amount_paise, Subscription.started_at, Subscription.expires_at, Subscription.status)
        .join(Subscription, Payment.subscription_id == Subscription.id)
        .join(Plan, Subscription.plan_id == Plan.id)
        .where(Payment.user_id == student_id, Payment.status == "success")
        .order_by(Payment.created_at.desc())
        .limit(10)
    )
    payment_history = [
        {
            "plan_name": r[0],
            "amount_paise": r[1],
            "started_at": r[2].isoformat() if r[2] else None,
            "expires_at": r[3].isoformat() if r[3] else None,
            "status": r[4],
        }
        for r in payments_result.all()
    ]

    activity: list[dict] = []
    watch_rows = await db.execute(
        select(Lesson.title, WatchHistory.last_watched_at)
        .join(WatchHistory, WatchHistory.lesson_id == Lesson.id)
        .where(WatchHistory.user_id == student_id)
        .order_by(WatchHistory.last_watched_at.desc())
        .limit(10)
    )
    for r in watch_rows.all():
        activity.append({"type": "video_watched", "title": r[0], "timestamp": r[1].isoformat()})

    test_rows = await db.execute(
        select(Test.title, TestAttempt.percentage, TestAttempt.completed_at)
        .join(TestAttempt, TestAttempt.test_id == Test.id)
        .where(TestAttempt.user_id == student_id)
        .order_by(TestAttempt.completed_at.desc())
        .limit(10)
    )
    for r in test_rows.all():
        activity.append({"type": "test_taken", "title": r[0], "score": float(r[1] or 0), "timestamp": r[2].isoformat()})

    activity.sort(key=lambda x: x["timestamp"], reverse=True)

    return {
        "id": user.id,
        "name": user.name,
        "phone": user.phone,
        "email": user.email,
        "avatar_url": user.avatar_url,
        "current_class": user.current_class,
        "medium": user.medium,
        "is_suspended": user.is_suspended,
        "suspended_reason": user.suspended_reason,
        "subscription_status": sub_status,
        "joined_at": user.created_at,
        "stats": {"videos": videos_watched, "tests": tests_taken, "avg_score": avg_score, "streak": 0},
        "subject_progress": subject_progress,
        "payment_history": payment_history,
        "recent_activity": activity[:20],
    }


async def export_students_csv(
    db: AsyncSession,
    class_number: int | None,
    subscription_status: str | None,
) -> str:
    now = datetime.now(timezone.utc)

    active_sub_sq = (
        select(Subscription.user_id)
        .where(Subscription.status == "active", or_(Subscription.expires_at.is_(None), Subscription.expires_at > now))
        .distinct().subquery()
    )
    active_trial_sq = (
        select(FreeTrial.user_id)
        .where(FreeTrial.expires_at > now, ~FreeTrial.user_id.in_(select(active_sub_sq.c.user_id)))
        .distinct().subquery()
    )

    base = select(User).where(User.role == "student")
    if class_number:
        base = base.where(User.current_class == class_number)
    if subscription_status == "active":
        base = base.where(User.id.in_(select(active_sub_sq.c.user_id)))
    elif subscription_status == "trial":
        base = base.where(User.id.in_(select(active_trial_sq.c.user_id)))

    users = (await db.execute(base.order_by(User.created_at.desc()))).scalars().all()

    watch_counts = {
        r[0]: r[1] for r in (
            await db.execute(
                select(WatchHistory.user_id, func.count(WatchHistory.id)).group_by(WatchHistory.user_id)
            )
        ).all()
    }
    test_stats = {
        r[0]: (r[1], float(r[2] or 0)) for r in (
            await db.execute(
                select(TestAttempt.user_id, func.count(TestAttempt.id), func.avg(TestAttempt.percentage))
                .group_by(TestAttempt.user_id)
            )
        ).all()
    }
    last_active = {
        r[0]: r[1] for r in (
            await db.execute(
                select(WatchHistory.user_id, func.max(WatchHistory.last_watched_at))
                .group_by(WatchHistory.user_id)
            )
        ).all()
    }
    active_sub_set: set[uuid.UUID] = {
        row[0] for row in (
            await db.execute(
                select(Subscription.user_id).where(
                    Subscription.status == "active",
                    or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
                )
            )
        ).all()
    }
    trial_set: set[uuid.UUID] = {
        row[0] for row in (
            await db.execute(select(FreeTrial.user_id).where(FreeTrial.expires_at > now))
        ).all()
    }

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Name", "Phone", "Email", "Class", "Medium",
        "Subscription Status", "Joined Date", "Last Active",
        "Videos Watched", "Tests Taken", "Avg Score",
    ])
    for u in users:
        sub_s = (
            "active" if u.id in active_sub_set
            else "trial" if u.id in trial_set
            else "free"
        )
        tests_taken, avg_score = test_stats.get(u.id, (0, 0.0))
        la = last_active.get(u.id)
        writer.writerow([
            u.name, u.phone or "", u.email or "", u.current_class or "", u.medium,
            sub_s, u.created_at.strftime("%Y-%m-%d"),
            la.strftime("%Y-%m-%d") if la else "",
            watch_counts.get(u.id, 0), tests_taken, f"{avg_score:.1f}",
        ])

    output.seek(0)
    return output.getvalue()
