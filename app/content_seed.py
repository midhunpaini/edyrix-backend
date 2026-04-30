import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.dev_seed import DEV_EMAIL
from app.logger import logger
from app.models.content import Chapter, Lesson, Subject
from app.models.progress import Test
from app.models.subscription import Plan, Subscription
from app.models.user import User

SEED_DATA_DIR = Path(__file__).resolve().parents[1] / "seed_data"


@dataclass(frozen=True)
class SubjectSeedConfig:
    source_slug: str
    path: Path
    subject_defaults: dict[str, Any]
    plan_defaults: dict[str, Any]


SEED_CONFIGS = [
    SubjectSeedConfig(
        source_slug="physics",
        path=SEED_DATA_DIR / "physics.json",
        subject_defaults={
            "name": "Physics",
            "name_ml": "Physics",
            "slug": "physics-10",
            "class_number": 10,
            "icon": "PHY",
            "color": "#0D6E6E",
            "monthly_price_paise": 24900,
            "is_active": True,
            "order_index": 1,
        },
        plan_defaults={
            "name": "Physics Class 10 - Monthly",
            "slug": "physics-10-monthly",
            "plan_type": "single_subject",
            "billing_cycle": "monthly",
            "price_paise": 24900,
            "original_price_paise": None,
            "description": "Monthly access to Class 10 Physics.",
            "features": ["All Physics chapters", "Chapter tests", "Class 10 SCERT-aligned content"],
            "is_active": True,
            "is_featured": False,
            "order_index": 10,
        },
    ),
    SubjectSeedConfig(
        source_slug="chemistry",
        path=SEED_DATA_DIR / "chemistry.json",
        subject_defaults={
            "name": "Chemistry",
            "name_ml": "രസതന്ത്രം",
            "slug": "chemistry-10",
            "class_number": 10,
            "icon": "CHEM",
            "color": "#7C3AED",
            "monthly_price_paise": 24900,
            "is_active": True,
            "order_index": 2,
        },
        plan_defaults={
            "name": "Chemistry Class 10 - Monthly",
            "slug": "chemistry-10-monthly",
            "plan_type": "single_subject",
            "billing_cycle": "monthly",
            "price_paise": 24900,
            "original_price_paise": None,
            "description": "Monthly access to Class 10 Chemistry.",
            "features": ["All Chemistry chapters", "Chapter tests", "Class 10 SCERT-aligned content"],
            "is_active": True,
            "is_featured": False,
            "order_index": 11,
        },
    ),
]


def _load_seed(config: SubjectSeedConfig) -> dict[str, Any]:
    with config.path.open(encoding="utf-8") as seed_file:
        data: dict[str, Any] = json.load(seed_file)
    _validate_seed_data(data, config)
    return data


def _validate_seed_data(data: dict[str, Any], config: SubjectSeedConfig) -> None:
    if data.get("subject_slug") != config.source_slug:
        raise ValueError(f"{config.source_slug} seed subject_slug must be {config.source_slug!r}")

    chapters = data.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise ValueError(f"{config.source_slug} seed must contain chapters")

    seen_chapters: set[int] = set()
    for chapter in chapters:
        chapter_number = chapter.get("chapter_number")
        if not isinstance(chapter_number, int):
            raise ValueError("chapter_number must be an integer")
        if chapter_number in seen_chapters:
            raise ValueError(f"duplicate chapter_number in {config.source_slug} seed: {chapter_number}")
        seen_chapters.add(chapter_number)

        if not chapter.get("title") or not chapter.get("title_ml"):
            raise ValueError(f"chapter {chapter_number} must have title and title_ml")

        lessons = chapter.get("lessons")
        if not isinstance(lessons, list) or len(lessons) != 5:
            raise ValueError(f"chapter {chapter_number} must have exactly 5 lessons")

        seen_lesson_orders: set[int] = set()
        for lesson in lessons:
            order_index = lesson.get("order_index")
            if not isinstance(order_index, int):
                raise ValueError(f"chapter {chapter_number} lesson order_index must be an integer")
            if order_index in seen_lesson_orders:
                raise ValueError(f"duplicate lesson order_index in chapter {chapter_number}: {order_index}")
            seen_lesson_orders.add(order_index)
            if not lesson.get("title") or not lesson.get("title_ml"):
                raise ValueError(f"chapter {chapter_number} lesson {order_index} must have title and title_ml")
            if not lesson.get("youtube_video_id"):
                raise ValueError(f"chapter {chapter_number} lesson {order_index} must have youtube_video_id")
            test = _lesson_test_data(chapter, lesson)
            _validate_test_data(test, f"{config.source_slug} chapter {chapter_number} lesson {order_index}")


def _lesson_test_data(chapter: dict[str, Any], lesson: dict[str, Any]) -> dict[str, Any]:
    test = lesson.get("test")
    if isinstance(test, dict):
        return test

    chapter_number = chapter["chapter_number"]
    order_index = lesson["order_index"]

    logger.warning(
        "Content seed chapter %s lesson %s is missing lesson-level test data; generating a development test",
        chapter_number,
        order_index,
    )

    if order_index == 5 and isinstance(chapter.get("test"), dict):
        legacy_test = chapter["test"]
        return {
            "title": f"{lesson['title']} - Test",
            "duration_minutes": legacy_test.get("duration_minutes", 10),
            "total_marks": legacy_test.get("total_marks", 0),
            "questions": legacy_test.get("questions", []),
        }

    chapter_title = chapter["title"]
    lesson_title = lesson["title"]
    return {
        "title": f"{lesson_title} - Test",
        "duration_minutes": 8,
        "total_marks": 3,
        "questions": [
            {
                "id": f"seed-c{chapter_number}-l{order_index}-q1",
                "text": "Which lesson is this test checking?",
                "text_ml": "Which lesson is this test checking?",
                "options": [
                    lesson_title,
                    f"{chapter_title} - Revision",
                    "Reflection of Light",
                    "Energy Management",
                ],
                "correct_answer": 0,
                "marks": 1,
                "explanation": f"This test is allocated to the lesson: {lesson_title}.",
            },
            {
                "id": f"seed-c{chapter_number}-l{order_index}-q2",
                "text": "This lesson belongs to which chapter?",
                "text_ml": "This lesson belongs to which chapter?",
                "options": [
                    chapter_title,
                    "Refraction of Light",
                    "Vision and the World of Colours",
                    "Energy Management",
                ],
                "correct_answer": 0,
                "marks": 1,
                "explanation": f"The lesson is part of the chapter {chapter_title}.",
            },
            {
                "id": f"seed-c{chapter_number}-l{order_index}-q3",
                "text": "What should you do before taking this lesson test?",
                "text_ml": "What should you do before taking this lesson test?",
                "options": [
                    "Complete the allocated lesson carefully",
                    "Skip the video and guess answers",
                    "Open a different chapter",
                    "Ignore the lesson concepts",
                ],
                "correct_answer": 0,
                "marks": 1,
                "explanation": "Lesson tests unlock after completing the allocated lesson, so review that lesson first.",
            },
        ],
    }


def _validate_test_data(test: dict[str, Any], context: str) -> None:
    questions = test.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError(f"{context} test must have questions")

    total_marks = test.get("total_marks")
    mark_sum = 0
    seen_questions: set[str] = set()
    for question in questions:
        question_id = question.get("id")
        if not isinstance(question_id, str) or not question_id:
            raise ValueError(f"{context} question id must be a non-empty string")
        if question_id in seen_questions:
            raise ValueError(f"duplicate question id in {context}: {question_id}")
        seen_questions.add(question_id)

        options = question.get("options")
        if not isinstance(options, list) or len(options) != 4:
            raise ValueError(f"{context} question {question_id} must have exactly 4 options")
        if question.get("correct_answer") not in range(4):
            raise ValueError(f"{context} question {question_id} correct_answer must be 0, 1, 2, or 3")
        mark_sum += int(question.get("marks", 1))

    if total_marks != mark_sum:
        logger.warning(
            "Content seed %s total_marks=%s differs from question marks sum=%s",
            context,
            total_marks,
            mark_sum,
        )


async def seed_content() -> None:
    if settings.APP_ENV != "development":
        return

    async with AsyncSessionLocal() as db:
        async with db.begin():
            for config in SEED_CONFIGS:
                data = _load_seed(config)
                stats = {
                    "chapters_created": 0,
                    "chapters_updated": 0,
                    "tests_created": 0,
                    "tests_updated": 0,
                    "lessons_created": 0,
                    "lessons_updated": 0,
                    "subscriptions_created": 0,
                    "subscriptions_updated": 0,
                }
                subject = await _ensure_subject(db, config)
                plan = await _ensure_plan(db, subject, config)
                await _ensure_dev_subscription(db, plan, stats, config)

                for chapter_data in data["chapters"]:
                    chapter = await _upsert_chapter(db, subject, chapter_data, stats)
                    for lesson_data in chapter_data["lessons"]:
                        lesson = await _upsert_lesson(db, chapter, lesson_data, stats)
                        await _upsert_test(
                            db,
                            subject,
                            chapter,
                            lesson,
                            _lesson_test_data(chapter_data, lesson_data),
                            stats,
                        )

                logger.info(
                    "%s content seed complete: chapters +%s/~%s, lessons +%s/~%s, tests +%s/~%s, "
                    "dev subscriptions +%s/~%s",
                    config.subject_defaults["name"],
                    stats["chapters_created"],
                    stats["chapters_updated"],
                    stats["lessons_created"],
                    stats["lessons_updated"],
                    stats["tests_created"],
                    stats["tests_updated"],
                    stats["subscriptions_created"],
                    stats["subscriptions_updated"],
                )


async def seed_physics_content() -> None:
    await seed_content()


async def _ensure_subject(db, config: SubjectSeedConfig, /) -> Subject:
    result = await db.execute(select(Subject).where(Subject.slug == config.subject_defaults["slug"]))
    subject = result.scalar_one_or_none()
    if subject is None:
        subject = Subject(**config.subject_defaults)
        db.add(subject)
        await db.flush()
        return subject

    for key, value in config.subject_defaults.items():
        setattr(subject, key, value)
    return subject


async def _ensure_plan(db, subject: Subject, config: SubjectSeedConfig, /) -> Plan:
    result = await db.execute(select(Plan).where(Plan.slug == config.plan_defaults["slug"]))
    plan = result.scalar_one_or_none()
    if plan is None:
        plan = Plan(**config.plan_defaults, subject_ids=[subject.id], class_numbers=None)
        db.add(plan)
        await db.flush()
        return plan

    for key, value in config.plan_defaults.items():
        setattr(plan, key, value)
    plan.subject_ids = [subject.id]
    plan.class_numbers = None
    return plan


async def _ensure_dev_subscription(
    db,
    plan: Plan,
    stats: dict[str, int],
    config: SubjectSeedConfig,
    /,
) -> None:
    user_result = await db.execute(select(User).where(User.email == DEV_EMAIL))
    user = user_result.scalar_one_or_none()
    if user is None:
        logger.warning(
            "Skipping %s dev subscription because %s does not exist",
            config.subject_defaults["name"],
            DEV_EMAIL,
        )
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
            config.plan_defaults["slug"],
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


async def _upsert_lesson(db, chapter: Chapter, lesson_data: dict[str, Any], stats: dict[str, int], /) -> Lesson:
    result = await db.execute(
        select(Lesson)
        .where(Lesson.chapter_id == chapter.id, Lesson.order_index == lesson_data["order_index"])
        .order_by(Lesson.created_at, Lesson.id)
    )
    lessons = list(result.scalars().all())
    if lessons:
        lesson = lessons[0]
        stats["lessons_updated"] += 1
        if len(lessons) > 1:
            logger.warning(
                "Found %s duplicate lessons for chapter %s order_index %s; updating oldest lesson %s",
                len(lessons) - 1,
                chapter.chapter_number,
                lesson_data["order_index"],
                lesson.id,
            )
    else:
        lesson = Lesson(chapter_id=chapter.id, title="", title_ml="", youtube_video_id="")
        db.add(lesson)
        stats["lessons_created"] += 1

    lesson.title = lesson_data["title"]
    lesson.title_ml = lesson_data["title_ml"]
    lesson.youtube_video_id = lesson_data["youtube_video_id"]
    lesson.duration_seconds = lesson_data.get("duration_seconds")
    lesson.is_free = lesson_data.get("is_free", False)
    lesson.thumbnail_url = lesson_data.get("thumbnail_url")
    lesson.order_index = lesson_data["order_index"]
    lesson.is_published = True
    await db.flush()
    return lesson


async def _upsert_test(
    db,
    subject: Subject,
    chapter: Chapter,
    lesson: Lesson,
    test_data: dict[str, Any],
    stats: dict[str, int],
    /,
) -> Test:
    result = await db.execute(
        select(Test).where(Test.lesson_id == lesson.id).order_by(Test.created_at, Test.id)
    )
    tests = list(result.scalars().all())
    if tests:
        test = tests[0]
        stats["tests_updated"] += 1
        if len(tests) > 1:
            logger.warning(
                "Found %s duplicate tests for chapter %s lesson %s; updating oldest test %s",
                len(tests) - 1,
                chapter.chapter_number,
                lesson.order_index,
                test.id,
            )
    else:
        test = Test(subject_id=subject.id, chapter_id=chapter.id, lesson_id=lesson.id, questions=[])
        db.add(test)
        stats["tests_created"] += 1

    test.subject_id = subject.id
    test.chapter_id = chapter.id
    test.lesson_id = lesson.id
    test.title = test_data["title"]
    test.duration_minutes = test_data["duration_minutes"]
    test.total_marks = test_data["total_marks"]
    test.questions = test_data["questions"]
    test.is_published = True
    await db.flush()
    return test
