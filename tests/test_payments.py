"""
Unit tests for payment_service HMAC functions.

Both verify_payment_signature and verify_webhook_signature are pure functions
(no DB, no Redis, no HTTP) — tested entirely in-process.
"""
import hashlib
import hmac

from app.config import settings
from app.services.payment_service import verify_payment_signature, verify_webhook_signature

# ── helpers ───────────────────────────────────────────────────────────────────

def _sign_payment(order_id: str, payment_id: str) -> str:
    msg = f"{order_id}|{payment_id}"
    return hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        msg.encode(),
        hashlib.sha256,
    ).hexdigest()


def _sign_webhook(body: bytes) -> str:
    return hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()


# ── payment signature ─────────────────────────────────────────────────────────

def test_payment_signature_valid():
    order_id = "order_TestABC123"
    payment_id = "pay_TestXYZ789"
    assert verify_payment_signature(order_id, payment_id, _sign_payment(order_id, payment_id))


def test_payment_signature_wrong_payment_id():
    order_id = "order_TestABC123"
    payment_id = "pay_TestXYZ789"
    sig = _sign_payment(order_id, payment_id)
    assert not verify_payment_signature(order_id, "pay_TAMPERED", sig)


def test_payment_signature_wrong_order_id():
    order_id = "order_TestABC123"
    payment_id = "pay_TestXYZ789"
    sig = _sign_payment(order_id, payment_id)
    assert not verify_payment_signature("order_TAMPERED", payment_id, sig)


def test_payment_signature_empty_string():
    assert not verify_payment_signature("order_x", "pay_x", "")


def test_payment_signature_all_zeros():
    assert not verify_payment_signature("order_x", "pay_x", "00" * 32)


def test_payment_signature_swapped_ids():
    order_id = "order_ABC"
    payment_id = "pay_XYZ"
    # Signing with swapped order must fail (the separator prevents prefix attacks)
    sig = _sign_payment(payment_id, order_id)
    assert not verify_payment_signature(order_id, payment_id, sig)


# ── webhook signature ─────────────────────────────────────────────────────────

def test_webhook_signature_valid():
    body = b'{"event":"payment.captured","payload":{"payment":{"entity":{"id":"pay_xxx"}}}}'
    assert verify_webhook_signature(body, _sign_webhook(body))


def test_webhook_signature_body_mismatch():
    body = b'{"event":"payment.captured"}'
    sig = _sign_webhook(body)
    assert not verify_webhook_signature(b'{"event":"payment.failed"}', sig)


def test_webhook_signature_tampered_body():
    body = b'{"event":"payment.captured","amount":39900}'
    sig = _sign_webhook(body)
    tampered = body.replace(b"39900", b"39901")  # change the amount by 1 paise
    assert not verify_webhook_signature(tampered, sig)


def test_webhook_signature_empty_body():
    body = b""
    assert verify_webhook_signature(body, _sign_webhook(body))


def test_webhook_signature_garbage():
    body = b'{"event":"payment.captured"}'
    assert not verify_webhook_signature(body, "deadbeef" * 8)
