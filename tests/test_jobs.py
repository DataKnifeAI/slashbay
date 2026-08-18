from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from slashbay.app import create_app
from slashbay.config import Settings
from slashbay.jobs.models import ProgressBody
from slashbay.jobs.queue import JobsQueue
from slashbay.service import Herald
from slashbay.state.models import RunStatus
from slashbay.state.store import MemoryStore
from slashbay.triage.providers import HeuristicTriage
from slashbay.webhooks.events import IssueEvent
from tests.conftest import GITHUB_SECRET, GITLAB_TOKEN, github_signature

WORKER_TOKEN = "worker-test-token"


class RecordingPublisher:
    def __init__(self) -> None:
        self.comments: list[str] = []
        self.labels: list[list[str]] = []

    async def comment(self, issue: IssueEvent, body: str) -> None:
        self.comments.append(body)

    async def label(self, issue: IssueEvent, labels: list[str]) -> None:
        self.labels.append(labels)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "dry_run": True,
        "state_dsn": "memory://",
        "repo_allowlist": "DataKnifeAI/*,dk-raas/*",
        "trigger_events": "opened,reopened",
        "github_webhook_secret": GITHUB_SECRET,
        "gitlab_webhook_token": GITLAB_TOKEN,
        "openai_api_key": "",
        "coder_access_url": "",
        "coder_token": "",
        "worker_token": WORKER_TOKEN,
    }
    values.update(overrides)
    return Settings(**values)


def _client(**overrides: object) -> TestClient:
    return TestClient(create_app(_settings(**overrides)))


def _issue_payload() -> dict:
    return {
        "action": "opened",
        "issue": {
            "number": 7,
            "title": "Fix the webhook retry loop",
            "body": (
                "When GitHub retries, Slashbay must not enqueue two jobs. "
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


def _post_github(client: TestClient, delivery: str = "deliv-1") -> dict:
    body = json.dumps(_issue_payload()).encode()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": github_signature(body),
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": delivery,
        },
    )
    assert response.status_code == 200
    return response.json()


def _auth(token: str = WORKER_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _actionable_issue() -> IssueEvent:
    return IssueEvent(
        platform="github",
        action="opened",
        owner="DataKnifeAI",
        repo="slashbay",
        number=11,
        title="Fix the webhook retry loop",
        body="When GitHub retries, Slashbay must not enqueue two jobs for one issue.",
        url="https://github.com/DataKnifeAI/slashbay/issues/11",
        clone_url="https://github.com/DataKnifeAI/slashbay.git",
    )


def test_claim_401_without_token() -> None:
    client = _client()
    response = client.get("/v1/jobs/claim", params={"workspace": "warm-1"})
    assert response.status_code == 401


def test_claim_401_wrong_token() -> None:
    client = _client()
    response = client.get(
        "/v1/jobs/claim",
        params={"workspace": "warm-1"},
        headers=_auth("nope"),
    )
    assert response.status_code == 401


def test_second_claim_204() -> None:
    client = _client()
    _post_github(client)
    first = client.get("/v1/jobs/claim", params={"workspace": "warm-1"}, headers=_auth())
    assert first.status_code == 200
    job = first.json()
    assert job["run_id"]
    assert job["git_url"].endswith("slashbay.git")
    assert job["command"][0:2] == ["agent", "-p"]
    assert "Fix the webhook retry loop" in job["prompt"]
    second = client.get("/v1/jobs/claim", params={"workspace": "warm-2"}, headers=_auth())
    assert second.status_code == 204


def test_duplicate_webhook_does_not_two_jobs() -> None:
    client = _client()
    first = _post_github(client, delivery="same-delivery")
    second = _post_github(client, delivery="same-delivery")
    assert first["run_id"] == second["run_id"]
    claimed = client.get("/v1/jobs/claim", params={"workspace": "warm-1"}, headers=_auth())
    assert claimed.status_code == 200
    empty = client.get("/v1/jobs/claim", params={"workspace": "warm-2"}, headers=_auth())
    assert empty.status_code == 204


def test_duplicate_issue_without_new_job() -> None:
    client = _client()
    first = _post_github(client, delivery="a")
    second = _post_github(client, delivery="b")
    assert first["run_id"] == second["run_id"]
    first_claim = client.get(
        "/v1/jobs/claim", params={"workspace": "w1"}, headers=_auth()
    )
    second_claim = client.get(
        "/v1/jobs/claim", params={"workspace": "w2"}, headers=_auth()
    )
    assert first_claim.status_code == 200
    assert second_claim.status_code == 204


@pytest.mark.asyncio
async def test_progress_claimed_comments_once() -> None:
    publisher = RecordingPublisher()
    settings = _settings()
    store = MemoryStore()
    queue = JobsQueue(settings, store, publisher)
    herald = Herald(settings, store, HeuristicTriage(), publisher, queue)
    run = await herald.handle(_actionable_issue(), delivery_id="d-11")
    assert run is not None
    assert run.status is RunStatus.queued
    assert any("queued for a warm workspace" in item for item in publisher.comments)

    job = await queue.claim("warm-alpha")
    assert job is not None
    claimed_comments = [c for c in publisher.comments if c.startswith("claimed by ")]
    assert claimed_comments == ["claimed by warm-alpha"]

    await queue.progress(job.id, ProgressBody(status="claimed", workspace="warm-alpha"))
    await queue.progress(job.id, ProgressBody(status="claimed", workspace="warm-alpha"))
    claimed_comments = [c for c in publisher.comments if c.startswith("claimed by ")]
    assert claimed_comments == ["claimed by warm-alpha"]

    before = len(publisher.comments)
    await queue.progress(job.id, ProgressBody(status="cloning"))
    await queue.progress(job.id, ProgressBody(status="agent_running"))
    assert len(publisher.comments) == before


@pytest.mark.asyncio
async def test_herald_enqueues_does_not_berth() -> None:
    class ExplodingCoder:
        async def create_workspace(self, **_kwargs):
            raise AssertionError("must not berth")

        async def start_workspace(self, *_args):
            raise AssertionError("must not berth")

        async def list_workspaces(self):
            return []

        async def health(self):
            return True

    publisher = RecordingPublisher()
    settings = _settings()
    store = MemoryStore()
    coder = ExplodingCoder()
    queue = JobsQueue(settings, store, publisher, coder)  # type: ignore[arg-type]
    herald = Herald(settings, store, HeuristicTriage(), publisher, queue)
    run = await herald.handle(_actionable_issue(), delivery_id="d-berth")
    assert run is not None
    assert run.status is RunStatus.queued
    assert run.workspace is None
    assert "dispatch" in run.extra
    assert run.extra["dispatch"]["command"][0:2] == ["agent", "-p"]
