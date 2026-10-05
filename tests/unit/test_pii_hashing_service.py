from __future__ import annotations

import pytest

from fry14_engine.pii.hashing_service import PIIHashingKeyMissingError, PIIHashingService


def test_hash_value_is_deterministic():
    service = PIIHashingService("test-key")
    assert service.hash_value("123-45-6789") == service.hash_value("123-45-6789")


def test_hash_value_normalizes_formatting():
    service = PIIHashingService("test-key")
    assert service.hash_value("123-45-6789") == service.hash_value("123456789")
    assert service.hash_value("abc") == service.hash_value("ABC")


def test_different_keys_produce_different_hashes():
    a = PIIHashingService("key-a")
    b = PIIHashingService("key-b")
    assert a.hash_value("123-45-6789") != b.hash_value("123-45-6789")


def test_hash_value_returns_hex_sha256_length():
    service = PIIHashingService("test-key")
    digest = service.hash_value("123-45-6789")
    assert len(digest) == 64
    int(digest, 16)  # raises ValueError if not valid hex


def test_empty_key_rejected():
    with pytest.raises(PIIHashingKeyMissingError):
        PIIHashingService("")


def test_hash_record_fields_leaves_non_pii_fields_untouched():
    service = PIIHashingService("test-key")
    data = {"loan_id": "LN-1", "borrower_tax_id": "123-45-6789", "borrower_legal_name": None}
    hashed = service.hash_record_fields(data, {"borrower_tax_id", "borrower_legal_name"})

    assert hashed["loan_id"] == "LN-1"
    assert hashed["borrower_tax_id"] != "123-45-6789"
    assert hashed["borrower_tax_id"] == service.hash_value("123-45-6789")
    assert hashed["borrower_legal_name"] is None  # null PII stays null, not hashed


def test_hash_record_fields_does_not_mutate_input():
    service = PIIHashingService("test-key")
    data = {"borrower_tax_id": "123-45-6789"}
    service.hash_record_fields(data, {"borrower_tax_id"})
    assert data["borrower_tax_id"] == "123-45-6789"


def test_from_env_raises_when_missing(monkeypatch):
    monkeypatch.delenv("FRY14_PII_HASH_KEY", raising=False)
    with pytest.raises(PIIHashingKeyMissingError):
        PIIHashingService.from_env()


def test_from_env_succeeds_when_set(monkeypatch):
    monkeypatch.setenv("FRY14_PII_HASH_KEY", "a-real-secret")
    service = PIIHashingService.from_env()
    assert service.hash_value("x") == PIIHashingService("a-real-secret").hash_value("x")
