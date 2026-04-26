import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.dev_seed import DEV_EMAIL
from app.logger import logger
from app.models.content import Chapter, Subject
from app.models.progress import Test
from app.models.subscription import Plan, Subscription
from app.models.user import User


PHYSICS_JSON_PATH = Path(__file__).resolve().parents[1] / "seed_data" / "physics.json"
SOURCE_SUBJECT_SLUG = "physics"
TARGET_SUBJECT_SLUG = "physics-10"
TARGET_PLAN_SLUG = "physics-10-monthly"

SUBJECT_DEFAULTS = {
    "name": "Physics",
    "name_ml": "Physics",
    "slug": TARGET_SUBJECT_SLUG,
    "class_number": 10,
    "icon": "PHY",
    "color": "#0D6E6E",
    "monthly_price_paise": 24900,
    "is_active": True,
    "order_index": 1,
}

PLAN_DEFAULTS = {
    "name": "Physics Class 10 - Monthly",
    "slug": TARGET_PLAN_SLUG,
    "plan_type": "single_subject",
    "billing_cycle": "monthly",
    "price_paise": 24900,
    "original_price_paise": None,
    "description": "Monthly access to Class 10 Physics.",
    "features": ["All Physics chapters", "Chapter tests", "Class 10 SCERT-aligned content"],
    "is_active": True,
    "is_featured": False,
    "order_index": 10,
}


def _load_physics_seed() -> dict[str, Any]:
    with PHYSICS_JSON_PATH.open(encoding="utf-8") as seed_file:
        data: dict[str, Any] = json.load(seed_file)
    _validate_seed_data(data)
    return data


def _validate_seed_data(data: dict[str, Any]) -> None:
    if data.get("subject_slug") != SOURCE_SUBJECT_SLUG:
        raise ValueError(f"physics seed subject_slug must be {SOURCE_SUBJECT_SLUG!r}")

    chapters = data.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise ValueError("physics seed must contain chapters")

    seen_chapters: set[int] = set()
    for chapter in chapters:
        chapter_number = chapter.get("chapter_number")
        if not isinstance(chapter_number, int):
            raise ValueError("chapter_number must be an integer")
        if chapter_number in seen_chapters:
            raise ValueError(f"duplicate chapter_number in physics seed: {chapter_number}")
        seen_chapters.add(chapter_number)

        if not chapter.get("title") or not chapter.get("title_ml"):
            raise ValueError(f"chapter {chapter_number} must have title and title_ml")

        test = chapter.get("test")
        if not isinstance(test, dict):
            raise ValueError(f"chapter {chapter_number} must have test data")
        questions = test.get("questions")
        if not isinstance(questions, list) or not questions:
            raise ValueError(f"chapter {chapter_number} test must have questions")

        total_marks = test.get("total_marks")
        mark_sum = 0
        seen_questions: set[str] = set()
        for question in questions:
            question_id = question.get("id")
            if not isinstance(question_id, str) or not question_id:
                raise ValueError(f"chapter {chapter_number} question id must be a non-empty string")
            if question_id in seen_questions:
                raise ValueError(f"duplicate question id in chapter {chapter_number}: {question_id}")
            seen_questions.add(question_id)

            options = question.get("options")
            if not isinstance(options, list) or len(options) != 4:
                raise ValueError(f"question {question_id} must have exactly 4 options")
            if question.get("correct_answer") not in range(4):
                raise ValueError(f"question {question_id} correct_answer must be 0, 1, 2, or 3")
            mark_sum += int(question.get("marks", 1))

        if total_marks != mark_sum:
            logger.warning(
                "Physics seed chapter %s total_marks=%s differs from question marks sum=%s",
                chapter_number,
                total_marks,
                mark_sum,
            )


async def seed_physics_content() -> None:
    if settings.APP_ENV != "development":
        return

    data = _load_physics_seed()
    stats = {
        "chapters_created": 0,
        "chapters_updated": 0,
        "tests_created": 0,
        "tests_updated": 0,
        "subscriptions_created": 0,
        "subscriptions_updated": 0,
    }

    async with AsyncSessionLocal() as db:
        async with db.begin():
            subject = await _ensure_subject(db)
            plan = await _ensure_plan(db, subject)
            await _ensure_dev_subscription(db, plan, stats)

            for chapter_data in data["chapters"]:
                chapter = await _upsert_chapter(db, subject, chapter_data, stats)
                await _upsert_test(db, chapter, chapter_data["test"], stats)

    logger.info(
        "Physics content seed complete: chapters +%s/~%s, tests +%s/~%s, dev subscriptions +%s/~%s",
        stats["chapters_created"],
        stats["chapters_updated"],
        stats["tests_created"],
        stats["tests_updated"],
        stats["subscriptions_created"],
        stats["subscriptions_updated"],
    )


async def _ensure_subject(db, /) -> Subject:
    result = await db.execute(select(Subject).where(Subject.slug == TARGET_SUBJECT_SLUG))
    subject = result.scalar_one_or_none()
    if subject is None:
        subject = Subject(**SUBJECT_DEFAULTS)
        db.add(subject)
        await db.flush()
        return subject

    for key, value in SUBJECT_DEFAULTS.items():
        setattr(subject, key, value)
    return subject


async def _ensure_plan(db, subject: Subject, /) -> Plan:
    result = await db.execute(select(Plan).where(Plan.slug == TARGET_PLAN_SLUG))
    plan = result.scalar_one_or_none()
    if plan is None:
        plan = Plan(**PLAN_DEFAULTS, subject_ids=[subject.id], class_numbers=None)
        db.add(plan)
        await db.flush()
        return plan

    for key, value in PLAN_DEFAULTS.items():
        setattr(plan, key, value)
    plan.subject_ids = [subject.id]
    plan.class_numbers = None
    return plan


async def _ensure_dev_subscription(db, plan: Plan, stats: dict[str, int], /) -> None:
    user_result = await db.execute(select(User).where(User.email == DEV_EMAIL))
    user = user_result.scalar_one_or_none()
    if user is None:
        logger.warning("Skipping Physics dev subscription because %s does not exist", DEV_EMAIL)
        return

    result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id, Subscription.plan_id == plan.id)
        .order_by(Subscription.created_at, Subscription.id)
    )
    subscriptions = list(result.scalars().all())
    if not subscriptions:
        db.add(Subscription(user_id=user.id, plan_id=plan.id, status="active", expires_at=None, auto_renew=False))
        stats["subscriptions_created"] += 1
        return

    primary = subscriptions[0]
    primary.status = "active"
    primary.expires_at = None
    primary.cancelled_at = None
    primary.auto_renew = False
    stats["subscriptions_updated"] += 1

    if len(subscriptions) > 1:
        logger.warning(
            "Found %s duplicate dev subscriptions for %s and %s; deactivating extras",
            len(subscriptions) - 1,
            DEV_EMAIL,
            TARGET_PLAN_SLUG,
        )
        for duplicate in subscriptions[1:]:
            duplicate.status = "cancelled"
            duplicate.auto_renew = False


async def _upsert_chapter(db, subject: Subject, chapter_data: dict[str, Any], stats: dict[str, int], /) -> Chapter:
    result = await db.execute(
        select(Chapter).where(
            Chapter.subject_id == subject.id,
            Chapter.chapter_number == chapter_data["chapter_number"],
        )
    )
    chapter = result.scalar_one_or_none()
    if chapter is None:
        chapter = Chapter(subject_id=subject.id, chapter_number=chapter_data["chapter_number"])
        db.add(chapter)
        stats["chapters_created"] += 1
    else:
        stats["chapters_updated"] += 1

    chapter.title = chapter_data["title"]
    chapter.title_ml = chapter_data["title_ml"]
    chapter.description = chapter_data.get("description")
    chapter.order_index = chapter_data.get("order_index", chapter_data["chapter_number"])
    chapter.is_published = True
    await db.flush()
    return chapter


async def _upsert_test(db, chapter: Chapter, test_data: dict[str, Any], stats: dict[str, int], /) -> Test:
    result = await db.execute(
        select(Test).where(Test.chapter_id == chapter.id).order_by(Test.created_at, Test.id)
    )
    tests = list(result.scalars().all())
    if tests:
        test = tests[0]
        stats["tests_updated"] += 1
        if len(tests) > 1:
            logger.warning(
                "Found %s duplicate tests for chapter %s; updating oldest test %s",
                len(tests) - 1,
                chapter.chapter_number,
                test.id,
            )
    else:
        test = Test(chapter_id=chapter.id, questions=[])
        db.add(test)
        stats["tests_created"] += 1

    test.title = test_data["title"]
    test.duration_minutes = test_data["duration_minutes"]
    test.total_marks = test_data["total_marks"]
    test.questions = test_data["questions"]
    test.is_published = True
    await db.flush()
    return test
