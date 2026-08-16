from __future__ import annotations

import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

from slashbay.app import create_app
from slashbay.config import Settings

GITHUB_SECRET = "github-test-secret"
GITLAB_TOKEN = "gitlab-test-token"


def github_signature(body: bytes, secret: str = GITHUB_SECRET) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        dry_run=True,
        state_dsn="memory://",
        repo_allowlist="DataKnifeAI/*,dk-raas/*",
        trigger_events="opened,reopened",
        github_webhook_secret=GITHUB_SECRET,
        gitlab_webhook_token=GITLAB_TOKEN,
        openai_api_key="",
        coder_access_url="",
        coder_token="",
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))
