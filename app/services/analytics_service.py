import json
import uuid
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Lesson, Subject
from app.models.progress import WatchHistory
from app.models.subscription import Plan, Subscription
from app.models.user import FreeTrial, User


async def get_dashboard_extended(db: AsyncSession, redis_client: Redis) -> dict:
    cache_key = "admin:dashboard:extended"
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    trial_total = (await db.execute(select(func.count()).select_from(FreeTrial))).scalar() or 0

    trial_converted = (
        await db.execute(
            select(func.count(func.distinct(FreeTrial.user_id)))
            .join(Subscription, Subscription.user_id == FreeTrial.user_id)
            .where(
                Subscription.status == "active",
                or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
            )
        )
    ).scalar() or 0

    conversion_rate = round((trial_converted / trial_total * 100), 1) if trial_total else 0

    trial_active = (
        await db.execute(
            select(func.count()).select_from(FreeTrial).where(FreeTrial.expires_at > now)
        )
    ).scalar() or 0

    churn = (
        await db.execute(
            select(func.count()).select_from(Subscription).where(
                Subscription.status == "cancelled",
                Subscription.cancelled_at >= month_start,
            )
        )
    ).scalar() or 0

    mrr_result = await db.execute(
        select(func.coalesce(func.sum(Plan.price_paise), 0))
        .join(Subscription, Subscription.plan_id == Plan.id)
        .where(
            Subscription.status == "active",
            or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
            Plan.billing_cycle != "one_time",
        )
    )
    mrr = mrr_result.scalar() or 0

    active_subs_count = (
        await db.execute(
            select(func.count()).select_from(Subscription).where(
                Subscription.status == "active",
                or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
            )
        )
    ).scalar() or 1

    plan_breakdown_result = await db.execute(
        select(Plan.name, func.count(Subscription.id), func.coalesce(func.sum(Plan.price_paise), 0))
        .join(Subscription, Subscription.plan_id == Plan.id)
        .where(
            Subscription.status == "active",
            or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
        )
        .group_by(Plan.name)
    )

    top_lessons_result = await db.execute(
        select(
            Lesson.id,
            Lesson.title,
            func.count(WatchHistory.id).label("views"),
            func.coalesce(func.avg(WatchHistory.watch_percentage), 0).label("avg_pct"),
        )
        .join(WatchHistory, WatchHistory.lesson_id == Lesson.id)
        .where(Lesson.is_deleted.is_(False))
        .group_by(Lesson.id, Lesson.title)
        .order_by(func.count(WatchHistory.id).desc())
        .limit(5)
    )

    low_lessons_result = await db.execute(
        select(
            Lesson.id,
            Lesson.title,
            func.count(WatchHistory.id).label("views"),
            func.coalesce(func.avg(WatchHistory.watch_percentage), 0).label("avg_pct"),
        )
        .join(WatchHistory, WatchHistory.lesson_id == Lesson.id)
        .where(Lesson.is_deleted.is_(False))
        .group_by(Lesson.id, Lesson.title)
        .having(func.avg(WatchHistory.watch_percentage) < 30)
        .order_by(func.avg(WatchHistory.watch_percentage))
        .limit(5)
    )

    subject_engagement_result = await db.execute(
        select(
            Subject.name,
            func.count(func.distinct(WatchHistory.user_id)).label("active_students"),
            func.coalesce(func.avg(WatchHistory.watch_percentage), 0).label("avg_pct"),
        )
        .outerjoin(Lesson, Lesson.subject_id == Subject.id)
        .outerjoin(WatchHistory, WatchHistory.lesson_id == Lesson.id)
        .where(Subject.is_active.is_(True))
        .group_by(Subject.name)
    )

    churn_rate = round((churn / active_subs_count) * 100, 1) if churn else 0

    result = {
        "trial_users": trial_active,
        "trial_conversion_rate": conversion_rate,
        "churn_this_month": churn,
        "churn_rate_pct": churn_rate,
        "mrr_paise": mrr,
        "arr_paise": mrr * 12,
        "revenue_by_plan": [
            {"plan_name": r[0], "count": r[1], "revenue_paise": r[2]}
            for r in plan_breakdown_result.all()
        ],
        "top_lessons": [
            {"id": str(r[0]), "title": r[1], "views": r[2], "completion_pct": round(float(r[3]), 1)}
            for r in top_lessons_result.all()
        ],
        "low_completion_lessons": [
            {"id": str(r[0]), "title": r[1], "views": r[2], "completion_pct": round(float(r[3]), 1)}
            for r in low_lessons_result.all()
        ],
        "subject_engagement": [
            {"subject": r[0], "active_students": r[1] or 0, "avg_completion_pct": round(float(r[2]), 1)}
            for r in subject_engagement_result.all()
        ],
    }

    await redis_client.setex(cache_key, 300, json.dumps(result))
    return result


async def get_content_stats(db: AsyncSession, redis_client: Redis, lesson_id: uuid.UUID) -> dict:
    cache_key = f"admin:content:stats:{lesson_id}"
    cached = await redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    rows = await db.execute(
        select(
            func.count(WatchHistory.id).label("total_views"),
            func.count(func.distinct(WatchHistory.user_id)).label("unique_viewers"),
            func.coalesce(func.avg(WatchHistory.watch_percentage), 0).label("avg_completion"),
            func.count(WatchHistory.id).filter(WatchHistory.watch_percentage >= 90).label("completed_count"),
        ).where(WatchHistory.lesson_id == lesson_id)
    )
    r = rows.one()
    total = r[0] or 0
    result = {
        "total_views": total,
        "unique_viewers": r[1] or 0,
        "avg_completion_pct": round(float(r[2] or 0), 1),
        "completion_rate": round((r[3] / total * 100) if total else 0, 1),
    }
    await redis_client.setex(cache_key, 3600, json.dumps(result))
    return result


async def get_revenue_data(
    db: AsyncSession,
    start_date: datetime,
    end_date: datetime,
    plan_id: uuid.UUID | None = None,
) -> dict:
    from app.models.subscription import Payment

    base_filters = [
        Payment.status == "success",
        Payment.created_at >= start_date,
        Payment.created_at <= end_date,
    ]
    if plan_id:
        base_filters.append(Payment.plan_id == plan_id)

    totals = await db.execute(
        select(
            func.coalesce(func.sum(Payment.amount_paise), 0),
            func.count(Payment.id).filter(Payment.status == "success"),
            func.count(Payment.id).filter(Payment.status == "failed"),
            func.coalesce(func.sum(Payment.amount_paise).filter(Payment.status == "refunded"), 0),
        ).where(
            Payment.created_at >= start_date,
            Payment.created_at <= end_date,
            *([Payment.plan_id == plan_id] if plan_id else []),
        )
    )
    t = totals.one()
    total_rev = int(t[0] or 0)
    refunded = int(t[3] or 0)

    daily_result = await db.execute(
        select(
            func.date(Payment.created_at).label("day"),
            func.sum(Payment.amount_paise).label("total"),
            func.count(Payment.id).label("cnt"),
        )
        .where(*base_filters)
        .group_by(func.date(Payment.created_at))
        .order_by(func.date(Payment.created_at))
    )

    plan_result = await db.execute(
        select(Plan.name, func.count(Payment.id), func.sum(Payment.amount_paise))
        .join(Payment, Payment.plan_id == Plan.id)
        .where(*base_filters)
        .group_by(Plan.name)
    )

    failed_count = (
        await db.execute(
            select(func.count(Payment.id)).where(
                Payment.status == "failed",
                Payment.created_at >= start_date,
                Payment.created_at <= end_date,
            )
        )
    ).scalar() or 0

    return {
        "total_revenue_paise": total_rev,
        "successful_payments": int(t[1] or 0),
        "failed_payments": failed_count,
        "refunded_paise": refunded,
        "net_revenue_paise": total_rev - refunded,
        "daily_breakdown": [
            {"date": r[0].strftime("%Y-%m-%d"), "revenue_paise": int(r[1] or 0), "count": int(r[2])}
            for r in daily_result.all()
        ],
        "plan_breakdown": [
            {"plan_name": r[0], "count": int(r[1]), "revenue_paise": int(r[2] or 0)}
            for r in plan_result.all()
        ],
    }


def compute_test_analytics(test, attempts: list) -> dict:
    attempt_count = len(attempts)
    if attempt_count == 0:
        return {"attempt_count": 0, "avg_score_pct": 0.0, "pass_rate": 0.0, "question_analytics": []}

    avg_score = round(sum(float(a[3] or 0) for a in attempts) / attempt_count, 1)
    pass_count = sum(1 for a in attempts if float(a[3] or 0) >= 50)
    pass_rate = round(pass_count / attempt_count * 100, 1)

    questions = test.questions or []
    opt_labels = ["A", "B", "C", "D"]
    q_analytics = []
    for i, q in enumerate(questions):
        q_id = q.get("id", str(i))
        correct_idx = q.get("correct_answer", 0)
        options = q.get("options", ["A", "B", "C", "D"])
        option_dist: dict[str, int] = {opt_labels[j]: 0 for j in range(len(options))}
        correct_count = 0
        for attempt in attempts:
            answers = attempt[0] or {}
            chosen = answers.get(q_id)
            if chosen is not None:
                label = opt_labels[chosen] if isinstance(chosen, int) and chosen < 4 else str(chosen)
                option_dist[label] = option_dist.get(label, 0) + 1
                if chosen == correct_idx:
                    correct_count += 1
        q_analytics.append({
            "question_index": i,
            "question_text": q.get("text", ""),
            "correct_rate": round(correct_count / attempt_count * 100, 1),
            "option_distribution": option_dist,
            "correct_option": opt_labels[correct_idx] if correct_idx < 4 else "A",
        })

    return {
        "attempt_count": attempt_count,
        "avg_score_pct": avg_score,
        "pass_rate": pass_rate,
        "question_analytics": q_analytics,
    }


async def get_dashboard_stats(db: AsyncSession) -> dict:
    from app.models.doubt import Doubt
    from app.models.subscription import Payment, Plan, Subscription

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    thirty_days_ago = now - timedelta(days=30)

    total_students = (
        await db.execute(select(func.count(User.id)).where(User.role == "student"))
    ).scalar() or 0

    active_subs = (
        await db.execute(
            select(func.count(Subscription.id)).where(
                Subscription.status == "active",
                or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
            )
        )
    ).scalar() or 0

    mrr_paise = (
        await db.execute(
            select(func.coalesce(func.sum(Plan.price_paise), 0))
            .join(Subscription, Subscription.plan_id == Plan.id)
            .where(
                Subscription.status == "active",
                or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
                Plan.billing_cycle != "one_time",
            )
        )
    ).scalar() or 0

    new_signups = (
        await db.execute(
            select(func.count(User.id)).where(
                User.role == "student", User.created_at >= today_start
            )
        )
    ).scalar() or 0

    pending_doubts = (
        await db.execute(select(func.count(Doubt.id)).where(Doubt.status == "pending"))
    ).scalar() or 0

    revenue_day_col = func.date(Payment.created_at).label("day")
    revenue_result = await db.execute(
        select(revenue_day_col, func.sum(Payment.amount_paise).label("total"))
        .where(Payment.status == "success", Payment.created_at >= thirty_days_ago)
        .group_by(revenue_day_col)
        .order_by(revenue_day_col)
    )
    revenue_last_30_days = [
        {"date": row.day.strftime("%Y-%m-%d"), "amount_paise": row.total}
        for row in revenue_result.all()
    ]

    return {
        "total_students": total_students,
        "active_subscriptions": active_subs,
        "mrr_paise": mrr_paise,
        "new_signups_today": new_signups,
        "pending_doubts": pending_doubts,
        "revenue_last_30_days": revenue_last_30_days,
    }


async def get_revenue_forecast(db: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    three_months_ago = now - timedelta(days=90)
    end_of_month = (now.replace(day=1) + timedelta(days=32)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )

    active_sub_q = select(func.count()).select_from(Subscription).where(
        Subscription.status == "active",
        or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
    )
    active_count = (await db.execute(active_sub_q)).scalar() or 1

    mrr_q = (
        select(func.coalesce(func.sum(Plan.price_paise), 0))
        .join(Subscription, Subscription.plan_id == Plan.id)
        .where(
            Subscription.status == "active",
            or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
            Plan.billing_cycle != "one_time",
        )
    )
    mrr = (await db.execute(mrr_q)).scalar() or 0

    expiring_this_month = (
        await db.execute(
            select(func.count()).select_from(Subscription).where(
                Subscription.expires_at >= now,
                Subscription.expires_at < end_of_month,
                Subscription.status == "active",
            )
        )
    ).scalar() or 0

    expired_3m = (
        await db.execute(
            select(func.count()).select_from(Subscription).where(
                Subscription.expires_at >= three_months_ago,
                Subscription.expires_at < now,
                Subscription.status.in_(["expired", "cancelled"]),
            )
        )
    ).scalar() or 0

    if expired_3m > 0:
        expired_user_sq = (
            select(Subscription.user_id)
            .where(
                Subscription.expires_at >= three_months_ago,
                Subscription.expires_at < now,
                Subscription.status.in_(["expired", "cancelled"]),
            )
            .subquery()
        )
        renewed_3m = (
            await db.execute(
                select(func.count(func.distinct(Subscription.user_id))).where(
                    Subscription.user_id.in_(select(expired_user_sq.c.user_id)),
                    Subscription.status == "active",
                    or_(Subscription.expires_at.is_(None), Subscription.expires_at > now),
                )
            )
        ).scalar() or 0
        renewal_rate = round(renewed_3m / expired_3m, 2)
    else:
        renewal_rate = 0.8

    projected_renewals = int(expiring_this_month * renewal_rate)
    avg_plan_price = int(mrr / active_count) if active_count else 39900
    at_risk = (expiring_this_month - projected_renewals) * avg_plan_price

    return {
        "current_mrr_paise": int(mrr),
        "projected_next_month_paise": int(mrr + projected_renewals * avg_plan_price),
        "subs_expiring_this_month": expiring_this_month,
        "historical_renewal_rate": renewal_rate,
        "projected_renewals": projected_renewals,
        "at_risk_revenue_paise": max(at_risk, 0),
    }
