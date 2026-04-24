"""
Seed initial subjects and plans.
Run once after migrations: uv run python seed.py
Safe to re-run — skips existing records by slug.
"""
import asyncio

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.content import Subject
from app.models.subscription import Plan

SUBJECTS = [
    # Class 10
    dict(name="Physics", name_ml="ഭൗതികശാസ്ത്രം", slug="physics-10", class_number=10,
         icon="⚛️", color="#0D6E6E", monthly_price_paise=24900, order_index=1),
    dict(name="Chemistry", name_ml="രസതന്ത്രം", slug="chemistry-10", class_number=10,
         icon="🧪", color="#7C3AED", monthly_price_paise=24900, order_index=2),
    dict(name="Biology", name_ml="ജീവശാസ്ത്രം", slug="biology-10", class_number=10,
         icon="🌿", color="#059669", monthly_price_paise=24900, order_index=3),
    dict(name="Mathematics", name_ml="ഗണിതശാസ്ത്രം", slug="maths-10", class_number=10,
         icon="📐", color="#F5A623", monthly_price_paise=24900, order_index=4),
    # Class 9
    dict(name="Physics", name_ml="ഭൗതികശാസ്ത്രം", slug="physics-9", class_number=9,
         icon="⚛️", color="#0D6E6E", monthly_price_paise=19900, order_index=1),
    dict(name="Chemistry", name_ml="രസതന്ത്രം", slug="chemistry-9", class_number=9,
         icon="🧪", color="#7C3AED", monthly_price_paise=19900, order_index=2),
    dict(name="Biology", name_ml="ജീവശാസ്ത്രം", slug="biology-9", class_number=9,
         icon="🌿", color="#059669", monthly_price_paise=19900, order_index=3),
]


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        # ── Subjects ──────────────────────────────────────────────────────────
        inserted_subjects: dict[str, Subject] = {}
        for data in SUBJECTS:
            existing = await db.execute(select(Subject).where(Subject.slug == data["slug"]))
            subject = existing.scalar_one_or_none()
            if subject is None:
                subject = Subject(**data)
                db.add(subject)
                await db.flush()
                print(f"  + Subject: {data['slug']}")
            else:
                print(f"  ~ Subject exists: {data['slug']}")
            inserted_subjects[data["slug"]] = subject

        await db.flush()

        # ── Plans ─────────────────────────────────────────────────────────────
        phy10 = inserted_subjects["physics-10"].id
        chem10 = inserted_subjects["chemistry-10"].id
        bio10 = inserted_subjects["biology-10"].id
        maths10 = inserted_subjects["maths-10"].id
        phy9 = inserted_subjects["physics-9"].id
        chem9 = inserted_subjects["chemistry-9"].id
        bio9 = inserted_subjects["biology-9"].id

        plans = [
            dict(
                name="Physics Class 10 — Monthly",
                slug="physics-10-monthly",
                plan_type="single_subject",
                billing_cycle="monthly",
                price_paise=24900,
                original_price_paise=None,
                subject_ids=[phy10],
                class_numbers=None,
                features=["All Physics chapters", "Video lessons", "Chapter tests", "PDF notes"],
                is_featured=False,
                order_index=10,
            ),
            dict(
                name="Chemistry Class 10 — Monthly",
                slug="chemistry-10-monthly",
                plan_type="single_subject",
                billing_cycle="monthly",
                price_paise=24900,
                original_price_paise=None,
                subject_ids=[chem10],
                class_numbers=None,
                features=["All Chemistry chapters", "Video lessons", "Chapter tests", "PDF notes"],
                is_featured=False,
                order_index=11,
            ),
            dict(
                name="Biology Class 10 — Monthly",
                slug="biology-10-monthly",
                plan_type="single_subject",
                billing_cycle="monthly",
                price_paise=24900,
                original_price_paise=None,
                subject_ids=[bio10],
                class_numbers=None,
                features=["All Biology chapters", "Video lessons", "Chapter tests", "PDF notes"],
                is_featured=False,
                order_index=12,
            ),
            dict(
                name="SSLC Science Bundle — Monthly",
                slug="sslc-science-bundle-monthly",
                plan_type="bundle",
                billing_cycle="monthly",
                price_paise=39900,
                original_price_paise=74700,
                subject_ids=[phy10, chem10, bio10],
                class_numbers=None,
                features=[
                    "Physics + Chemistry + Biology",
                    "All chapters & video lessons",
                    "Chapter tests & PDF notes",
                    "Save ₹348/year vs individual",
                ],
                is_featured=True,
                order_index=1,
            ),
            dict(
                name="SSLC Complete Class 10 — Monthly",
                slug="sslc-complete-monthly",
                plan_type="complete",
                billing_cycle="monthly",
                price_paise=49900,
                original_price_paise=99600,
                subject_ids=None,
                class_numbers=[10],
                features=[
                    "All Class 10 subjects",
                    "Physics, Chemistry, Biology, Maths",
                    "Unlimited access for 30 days",
                    "PDF notes & tests included",
                ],
                is_featured=False,
                order_index=2,
            ),
            dict(
                name="Full Access — Monthly",
                slug="full-access-monthly",
                plan_type="full_access",
                billing_cycle="monthly",
                price_paise=99900,
                original_price_paise=None,
                subject_ids=None,
                class_numbers=None,
                features=[
                    "All classes (7–10)",
                    "All subjects unlimited",
                    "Priority doubt support",
                    "Best value for families",
                ],
                is_featured=False,
                order_index=3,
            ),
            dict(
                name="SSLC Science Bundle — Lifetime",
                slug="sslc-science-bundle-lifetime",
                plan_type="lifetime",
                billing_cycle="one_time",
                price_paise=499900,
                original_price_paise=999900,
                subject_ids=[phy10, chem10, bio10],
                class_numbers=None,
                features=[
                    "Physics + Chemistry + Biology",
                    "Lifetime access — pay once",
                    "All future content updates",
                    "Priority doubt support",
                ],
                is_featured=False,
                order_index=5,
            ),
        ]

        for data in plans:
            existing = await db.execute(select(Plan).where(Plan.slug == data["slug"]))
            if existing.scalar_one_or_none() is None:
                db.add(Plan(**data))
                print(f"  + Plan: {data['slug']}")
            else:
                print(f"  ~ Plan exists: {data['slug']}")

        await db.commit()
        print("\nSeed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
