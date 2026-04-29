import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Plan, Subscription
from app.models.user import FreeTrial, User


class AccessDenied(Exception):
    """Raised when a user attempts to access gated content without a valid entitlement."""

    def __init__(self, subject_id: uuid.UUID, class_number: int) -> None:
        self.subject_id = subject_id
        self.class_number = class_number


@dataclass(frozen=True)
class UserEntitlements:
    is_admin: bool
    has_trial: bool
    has_full_access: bool
    entitled_class_numbers: frozenset[int]
    entitled_subject_ids: frozenset[uuid.UUID]

    @classmethod
    def anonymous(cls) -> "UserEntitlements":
        return cls(
            is_admin=False,
            has_trial=False,
            has_full_access=False,
            entitled_class_numbers=frozenset(),
            entitled_subject_ids=frozenset(),
        )


async def _build_entitlements(db: AsyncSession, user: User) -> UserEntitlements:
    if user.role == "admin":
        return UserEntitlements(
            is_admin=True,
            has_trial=False,
            has_full_access=True,
            entitled_class_numbers=frozenset(range(7, 11)),
            entitled_subject_ids=frozenset(),
        )

    now = datetime.now(timezone.utc)

    trial_result = await db.execute(
        select(FreeTrial).where(
            FreeTrial.user_id == user.id,
            FreeTrial.expires_at > now,
        )
    )
    has_trial = trial_result.scalar_one_or_none() is not None

    subs_result = await db.execute(
        select(Subscription, Plan)
        .join(Plan, Subscription.plan_id == Plan.id)
        .where(
            Subscription.user_id == user.id,
            Subscription.status == "active",
            or_(
                Subscription.expires_at.is_(None),
                Subscription.expires_at > now,
            ),
        )
    )

    has_full_access = False
    class_numbers: set[int] = set()
    subject_ids: set[uuid.UUID] = set()

    for _sub, plan in subs_result.all():
        if plan.plan_type == "full_access":
            has_full_access = True
        elif plan.plan_type in ("complete", "seasonal"):
            if plan.class_numbers:
                class_numbers.update(plan.class_numbers)
        elif plan.plan_type in ("bundle", "single_subject", "lifetime"):
            if plan.subject_ids:
                subject_ids.update(plan.subject_ids)

    return UserEntitlements(
        is_admin=False,
        has_trial=has_trial,
        has_full_access=has_full_access,
        entitled_class_numbers=frozenset(class_numbers),
        entitled_subject_ids=frozenset(subject_ids),
    )


class ContentAccessPolicy:
    """Single policy layer for all content access decisions.

    Construct once per request via ``await ContentAccessPolicy.build(db, user)``,
    then pass the instance into every service function that needs to gate content.
    All decision methods are synchronous — no DB calls after construction.

    Adding a new entitlement type (coupon, gifted access, etc.) means:
      1. Add a field to UserEntitlements
      2. Populate it in _build_entitlements
      3. Check it in can_access_subject
    No routes or service functions need to change.
    """

    __slots__ = ("_ent",)

    def __init__(self, entitlements: UserEntitlements) -> None:
        self._ent = entitlements

    @classmethod
    def anonymous(cls) -> "ContentAccessPolicy":
        return cls(UserEntitlements.anonymous())

    @classmethod
    async def build(cls, db: AsyncSession, user: User) -> "ContentAccessPolicy":
        return cls(await _build_entitlements(db, user))

    # ── subject-level ──────────────────────────────────────────────────────────

    def can_access_subject(self, subject_id: uuid.UUID, class_number: int) -> bool:
        e = self._ent
        return (
            e.is_admin
            or e.has_trial
            or e.has_full_access
            or class_number in e.entitled_class_numbers
            or subject_id in e.entitled_subject_ids
        )

    # ── lesson-level — source of truth for all content ─────────────────────────

    def can_access_lesson(
        self, lesson_is_free: bool, subject_id: uuid.UUID, class_number: int
    ) -> bool:
        """Free lessons are accessible to all. Premium lessons require subject entitlement."""
        if lesson_is_free:
            return True
        return self.can_access_subject(subject_id, class_number)

    def assert_lesson_access(
        self, lesson_is_free: bool, subject_id: uuid.UUID, class_number: int
    ) -> None:
        if not self.can_access_lesson(lesson_is_free, subject_id, class_number):
            raise AccessDenied(subject_id, class_number)

    # ── dependent resources inherit from lesson ────────────────────────────────

    def assert_note_access(self, subject_id: uuid.UUID, class_number: int) -> None:
        """Notes inherit subject-level access. There is no free tier for notes."""
        if not self.can_access_subject(subject_id, class_number):
            raise AccessDenied(subject_id, class_number)
