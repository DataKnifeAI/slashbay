"""Webhook authenticity checks. Secrets stay in env; never log them."""

from __future__ import annotations

import hashlib
import hmac


def verify_github_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """GitHub `X-Hub-Signature-256: sha256=<hex>` HMAC of the raw body."""
    if not secret or not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    expected = f"sha256={digest}"
    return hmac.compare_digest(expected, signature_header)


def verify_gitlab_token(expected: str, provided: str | None) -> bool:
    """GitLab `X-Gitlab-Token` compared to `GITLAB_WEBHOOK_TOKEN`."""
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided)
