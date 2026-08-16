from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from slashbay.coder.client import CoderClient
from slashbay.comments.publisher import build_publisher
from slashbay.config import Settings, get_settings
from slashbay.service import Herald
from slashbay.state.store import build_store
from slashbay.triage.providers import build_triage
from slashbay.webhooks.events import parse_github_issue_event, parse_gitlab_issue_event
from slashbay.webhooks.signatures import verify_github_signature, verify_gitlab_token

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = build_store(settings.state_dsn)
    triage = build_triage(settings)
    publisher = build_publisher(settings)
    coder = None
    if not settings.dry_run and settings.coder_access_url and settings.coder_token:
        coder = CoderClient(settings)

    herald = Herald(settings, store, triage, publisher, coder)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        log.info("slashbay up dry_run=%s template=%s", settings.dry_run, settings.coder_template)
        yield
        if coder is not None:
            await coder.aclose()

    app = FastAPI(
        title="Slashbay",
        description="DataKnifeAI issue-webhook herald",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.store = store
    app.state.herald = herald

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhooks/github")
    async def github_webhook(
        request: Request,
        x_hub_signature_256: str | None = Header(default=None),
        x_github_event: str | None = Header(default=None),
    ) -> JSONResponse:
        body = await request.body()
        if not verify_github_signature(settings.github_webhook_secret, body, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="invalid github signature")
        if x_github_event == "ping":
            return JSONResponse({"accepted": True, "reason": "ping"})
        payload = json.loads(body or b"{}")
        issue = parse_github_issue_event(payload)
        run = await herald.handle(issue)
        return _run_response(run, ignored_if_none=issue is None)

    @app.post("/webhooks/gitlab")
    async def gitlab_webhook(
        request: Request,
        x_gitlab_token: str | None = Header(default=None),
        x_gitlab_event: str | None = Header(default=None),
    ) -> JSONResponse:
        if not verify_gitlab_token(settings.gitlab_webhook_token, x_gitlab_token):
            raise HTTPException(status_code=401, detail="invalid gitlab token")
        payload = await request.json()
        if (x_gitlab_event or "").lower() == "push hook":
            return JSONResponse({"accepted": False, "reason": "ignored event"})
        issue = parse_gitlab_issue_event(payload)
        run = await herald.handle(issue)
        return _run_response(run, ignored_if_none=issue is None)

    return app


def _run_response(run: Any, *, ignored_if_none: bool) -> JSONResponse:
    if run is None:
        return JSONResponse({"accepted": False, "reason": "ignored event"})
    accepted = run.status.value not in {"ignored"}
    return JSONResponse(
        {
            "accepted": accepted and not ignored_if_none,
            "run_id": run.id,
            "status": run.status.value,
            "reason": run.error or None,
        }
    )


app = create_app()
