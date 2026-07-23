"""HMAC-SHA256 webhook signature verification.

GitHub signs each delivery with the app's webhook secret and sends the digest in the
X-Hub-Signature-256 header as 'sha256=<hex>'. We recompute it over the raw body and
compare in constant time. Forged deliveries are rejected before any work happens
(ARCHITECTURE §3.1)."""

from __future__ import annotations

import hashlib
import hmac


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    if not secret or not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    sent = signature_header.removeprefix("sha256=")
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sent, expected)
