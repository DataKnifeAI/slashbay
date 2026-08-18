from __future__ import annotations

import json

from fastapi.testclient import TestClient

from tests.conftest import github_signature


def _issue_payload(**overrides: object) -> dict:
    payload = {
        "action": "opened",
        "issue": {
            "number": 7,
            "title": "Fix the webhook retry loop",
            "body": (
                "When GitHub retries, Slashbay double-berths a workspace. "
                "Deduplicate on delivery id."
            ),
            "html_url": "https://github.com/DataKnifeAI/slashbay/issues/7",
            "labels": [],
        },
        "repository": {
            "full_name": "DataKnifeAI/slashbay",
            "clone_url": "https://github.com/DataKnifeAI/slashbay.git",
        },
    }
    payload.update(overrides)
    return payload


def test_github_rejects_bad_signature(client: TestClient) -> None:
    body = json.dumps(_issue_payload()).encode()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=deadbeef",
            "X-GitHub-Event": "issues",
        },
    )
    assert response.status_code == 401


def test_github_rejects_missing_signature(client: TestClient) -> None:
    body = json.dumps(_issue_payload()).encode()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"Content-Type": "application/json", "X-GitHub-Event": "issues"},
    )
    assert response.status_code == 401


def test_github_accepts_signed_issue(client: TestClient) -> None:
    body = json.dumps(_issue_payload()).encode()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": github_signature(body),
            "X-GitHub-Event": "issues",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] is True
    assert data["status"] in {"queued", "commented", "triaged"}
    assert data["run_id"]
