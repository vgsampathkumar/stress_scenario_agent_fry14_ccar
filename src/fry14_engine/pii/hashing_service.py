"""PII Detection & Hashing Service (C7): deterministic, keyed one-way
hashing of PII fields. See 02-design-document.md §3.3 and requirement 2.3
("PII Obfuscation").

PII fields are identified by contract annotation (`pii: true`), not
inferred by pattern-matching — deterministic and auditable, per the design
doc. This module only does the hashing; field identification is the
caller's job (it already has the contract).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from typing import Any

_DEFAULT_KEY_ENV_VAR = "FRY14_PII_HASH_KEY"
_NON_ALPHANUMERIC_RE = re.compile(r"[^A-Za-z0-9]")


class PIIHashingKeyMissingError(Exception):
    pass


def _normalize(value: str) -> str:
    """Strip formatting (dashes, spaces, punctuation) and uppercase, so
    equivalent values — e.g. "123-45-6789" and "123456789" — hash to the
    same key."""
    return _NON_ALPHANUMERIC_RE.sub("", value).upper()


class PIIHashingService:
    def __init__(self, secret_key: bytes | str) -> None:
        if isinstance(secret_key, str):
            secret_key = secret_key.encode("utf-8")
        if not secret_key:
            raise PIIHashingKeyMissingError("PII hashing key must not be empty")
        self._secret_key = secret_key

    @classmethod
    def from_env(cls, env_var: str = _DEFAULT_KEY_ENV_VAR) -> PIIHashingService:
        """The production path: the key must come from a secrets manager /
        environment injection, never a hardcoded default. See
        01-approach-paper.md §6 (Security & Privacy NFRs)."""
        key = os.environ.get(env_var)
        if not key:
            raise PIIHashingKeyMissingError(
                f"Environment variable {env_var} is not set. The PII hashing key must be "
                "injected via a secrets manager / environment variable, never hardcoded."
            )
        return cls(key)

    def hash_value(self, value: str) -> str:
        """Deterministic: the same value always hashes to the same digest
        under this key, so the hash can be used as a stable join key."""
        normalized = _normalize(value)
        return hmac.new(self._secret_key, normalized.encode("utf-8"), hashlib.sha256).hexdigest()

    def hash_record_fields(self, data: dict[str, Any], pii_fields: set[str]) -> dict[str, Any]:
        """Return a new dict with every field in `pii_fields` replaced by
        its hash. A `None` value stays `None` — there is nothing to hash,
        and a null PII field is a nullability concern for the contract,
        not this service."""
        hashed = dict(data)
        for field_name in pii_fields:
            value = hashed.get(field_name)
            if value is not None:
                hashed[field_name] = self.hash_value(str(value))
        return hashed
