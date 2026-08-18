from __future__ import annotations

import hmac

from fastapi import HTTPException


def verify_worker_bearer(authorization: str | None, expected: str) -> None:
    """Require `Authorization: Bearer <SLASHBAY_WORKER_TOKEN>`."""
    if not expected:
        raise HTTPException(status_code=401, detail="invalid worker token")
    if not authorization:
        raise HTTPException(status_code=401, detail="invalid worker token")
    scheme, _, token = authorization.partition(" ")
    provided = token.strip() if scheme.lower() == "bearer" else ""
    if len(provided) != len(expected) or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid worker token")
