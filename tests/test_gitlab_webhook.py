from __future__ import annotations

import json

from fastapi.testclient import TestClient

from tests.conftest import GITLAB_TOKEN


def _issue_payload() -> dict:
    return {
        "object_kind": "issue",
        "event_type": "issue",
        "project": {
            "id": 42,
            "path_with_namespace": "dk-raas/slashbay",
            "http_url": "https://gitlab.com/dk-raas/slashbay.git",
        },
        "object_attributes": {
            "action": "open",
            "iid": 3,
            "title": "Webhook token should be compared in constant time",
            "description": (
                "Use hmac.compare_digest for X-Gitlab-Token so timing leaks stay boring."
            ),
            "url": "https://gitlab.com/dk-raas/slashbay/-/issues/3",
        },
        "labels": [],
    }


def test_gitlab_rejects_bad_token(client: TestClient) -> None:
    body = json.dumps(_issue_payload()).encode()
    response = client.post(
        "/webhooks/gitlab",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Gitlab-Token": "nope",
            "X-Gitlab-Event": "Issue Hook",
        },
    )
    assert response.status_code == 401


def test_gitlab_rejects_missing_token(client: TestClient) -> None:
    body = json.dumps(_issue_payload()).encode()
    response = client.post(
        "/webhooks/gitlab",
        content=body,
        headers={"Content-Type": "application/json", "X-Gitlab-Event": "Issue Hook"},
    )
    assert response.status_code == 401


def test_gitlab_accepts_valid_token(client: TestClient) -> None:
    body = json.dumps(_issue_payload()).encode()
    response = client.post(
        "/webhooks/gitlab",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Gitlab-Token": GITLAB_TOKEN,
            "X-Gitlab-Event": "Issue Hook",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] is True
    assert data["run_id"]
