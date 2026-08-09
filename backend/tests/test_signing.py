"""Controlled export integrity-envelope tests."""

from app.services.signing import (
    canonical_json_bytes,
    sign_integrity_payload,
    verify_integrity_payload,
)


def test_integrity_signature_is_deterministic_and_order_independent():
    key = "k" * 48
    first = {"b": 2, "a": {"x": 1}}
    second = {"a": {"x": 1}, "b": 2}

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    signature = sign_integrity_payload(first, key)
    assert signature == sign_integrity_payload(second, key)
    assert verify_integrity_payload(second, signature["value"], key) is True


def test_integrity_signature_detects_tampering():
    key = "k" * 48
    payload = {"decision": "approved", "score": 82}
    signature = sign_integrity_payload(payload, key)

    payload["score"] = 28
    assert verify_integrity_payload(payload, signature["value"], key) is False
