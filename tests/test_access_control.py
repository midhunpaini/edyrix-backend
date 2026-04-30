"""
Unit tests for ContentAccessPolicy — the core content entitlement system.

These tests are pure Python: no DB, no Redis, no HTTP.
UserEntitlements is constructed directly to isolate the decision logic
from the DB query that normally builds it.
"""
import uuid

import pytest

from app.utils.access_control import AccessDenied, ContentAccessPolicy, UserEntitlements

SUBJECT_A = uuid.uuid4()
SUBJECT_B = uuid.uuid4()
CLASS_10 = 10
CLASS_9 = 9


def _policy(
    is_admin: bool = False,
    has_trial: bool = False,
    has_full_access: bool = False,
    class_numbers: frozenset[int] = frozenset(),
    subject_ids: frozenset[uuid.UUID] = frozenset(),
) -> ContentAccessPolicy:
    return ContentAccessPolicy(
        UserEntitlements(
            is_admin=is_admin,
            has_trial=has_trial,
            has_full_access=has_full_access,
            entitled_class_numbers=class_numbers,
            entitled_subject_ids=subject_ids,
        )
    )


# ── admin ─────────────────────────────────────────────────────────────────────

def test_admin_accesses_any_subject():
    p = _policy(is_admin=True)
    assert p.can_access_subject(SUBJECT_A, CLASS_10)
    assert p.can_access_subject(SUBJECT_B, CLASS_9)
    assert p.can_access_subject(uuid.uuid4(), 7)


def test_admin_accesses_premium_lesson():
    p = _policy(is_admin=True)
    assert p.can_access_lesson(lesson_is_free=False, subject_id=SUBJECT_A, class_number=CLASS_10)


def test_admin_assert_lesson_does_not_raise():
    p = _policy(is_admin=True)
    p.assert_lesson_access(False, SUBJECT_A, CLASS_10)


# ── anonymous / no entitlements ───────────────────────────────────────────────

def test_anonymous_blocks_premium_subject():
    p = ContentAccessPolicy.anonymous()
    assert not p.can_access_subject(SUBJECT_A, CLASS_10)


def test_anonymous_allows_free_lesson():
    p = ContentAccessPolicy.anonymous()
    assert p.can_access_lesson(lesson_is_free=True, subject_id=SUBJECT_A, class_number=CLASS_10)


def test_anonymous_blocks_premium_lesson():
    p = ContentAccessPolicy.anonymous()
    assert not p.can_access_lesson(lesson_is_free=False, subject_id=SUBJECT_A, class_number=CLASS_10)


def test_anonymous_assert_lesson_raises_on_premium():
    p = ContentAccessPolicy.anonymous()
    with pytest.raises(AccessDenied):
        p.assert_lesson_access(False, SUBJECT_A, CLASS_10)


def test_anonymous_assert_note_raises():
    p = ContentAccessPolicy.anonymous()
    with pytest.raises(AccessDenied):
        p.assert_note_access(SUBJECT_A, CLASS_10)


# ── free trial ────────────────────────────────────────────────────────────────

def test_trial_unlocks_all_subjects():
    p = _policy(has_trial=True)
    assert p.can_access_subject(SUBJECT_A, CLASS_10)
    assert p.can_access_subject(SUBJECT_B, CLASS_9)
    assert p.can_access_subject(uuid.uuid4(), 7)


def test_trial_unlocks_premium_lesson():
    p = _policy(has_trial=True)
    assert p.can_access_lesson(lesson_is_free=False, subject_id=SUBJECT_A, class_number=CLASS_10)


def test_trial_assert_lesson_does_not_raise():
    p = _policy(has_trial=True)
    p.assert_lesson_access(False, SUBJECT_A, CLASS_10)


# ── full_access plan ──────────────────────────────────────────────────────────

def test_full_access_unlocks_everything():
    p = _policy(has_full_access=True)
    assert p.can_access_subject(SUBJECT_A, CLASS_10)
    assert p.can_access_subject(uuid.uuid4(), 7)


# ── complete / seasonal (class-level entitlement) ─────────────────────────────

def test_class_plan_allows_own_class():
    p = _policy(class_numbers=frozenset({CLASS_10}))
    assert p.can_access_subject(SUBJECT_A, CLASS_10)
    assert p.can_access_subject(SUBJECT_B, CLASS_10)


def test_class_plan_blocks_other_class():
    p = _policy(class_numbers=frozenset({CLASS_10}))
    assert not p.can_access_subject(uuid.uuid4(), CLASS_9)


def test_class_plan_multiple_classes():
    p = _policy(class_numbers=frozenset({CLASS_10, CLASS_9}))
    assert p.can_access_subject(uuid.uuid4(), CLASS_10)
    assert p.can_access_subject(uuid.uuid4(), CLASS_9)
    assert not p.can_access_subject(uuid.uuid4(), 8)


# ── bundle / single_subject / lifetime (subject-level entitlement) ─────────────

def test_subject_plan_allows_entitled_subject():
    p = _policy(subject_ids=frozenset({SUBJECT_A}))
    assert p.can_access_subject(SUBJECT_A, CLASS_10)


def test_subject_plan_blocks_other_subject():
    p = _policy(subject_ids=frozenset({SUBJECT_A}))
    assert not p.can_access_subject(SUBJECT_B, CLASS_10)


def test_subject_plan_does_not_care_about_class():
    p = _policy(subject_ids=frozenset({SUBJECT_A}))
    assert p.can_access_subject(SUBJECT_A, CLASS_9)


# ── assert_lesson_access ──────────────────────────────────────────────────────

def test_assert_lesson_free_never_raises():
    p = ContentAccessPolicy.anonymous()
    p.assert_lesson_access(True, SUBJECT_A, CLASS_10)  # no raise


def test_assert_lesson_premium_raises_without_entitlement():
    p = _policy()
    with pytest.raises(AccessDenied) as exc_info:
        p.assert_lesson_access(False, SUBJECT_A, CLASS_10)
    assert exc_info.value.subject_id == SUBJECT_A
    assert exc_info.value.class_number == CLASS_10


def test_assert_lesson_premium_passes_with_subject_plan():
    p = _policy(subject_ids=frozenset({SUBJECT_A}))
    p.assert_lesson_access(False, SUBJECT_A, CLASS_10)  # no raise


# ── assert_note_access ────────────────────────────────────────────────────────

def test_assert_note_raises_without_entitlement():
    p = _policy()
    with pytest.raises(AccessDenied):
        p.assert_note_access(SUBJECT_A, CLASS_10)


def test_assert_note_passes_with_trial():
    p = _policy(has_trial=True)
    p.assert_note_access(SUBJECT_A, CLASS_10)  # no raise


def test_assert_note_passes_with_class_plan():
    p = _policy(class_numbers=frozenset({CLASS_10}))
    p.assert_note_access(SUBJECT_A, CLASS_10)  # no raise


def test_assert_note_blocks_when_only_other_class_entitled():
    p = _policy(class_numbers=frozenset({CLASS_9}))
    with pytest.raises(AccessDenied):
        p.assert_note_access(SUBJECT_A, CLASS_10)


# ── combined entitlements ─────────────────────────────────────────────────────

def test_subject_and_class_entitlements_combined():
    p = _policy(
        subject_ids=frozenset({SUBJECT_A}),
        class_numbers=frozenset({CLASS_9}),
    )
    assert p.can_access_subject(SUBJECT_A, CLASS_10)   # via subject
    assert p.can_access_subject(uuid.uuid4(), CLASS_9)  # via class
    assert not p.can_access_subject(uuid.uuid4(), CLASS_10)  # neither


def test_trial_plus_expired_plan_still_grants_access():
    # Trial alone is sufficient — expired class subscription doesn't matter
    p = _policy(has_trial=True)
    assert p.can_access_subject(SUBJECT_B, CLASS_10)
