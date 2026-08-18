from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from slashbay.config import Platform
from slashbay.triage.models import TriageResult


class RunStatus(StrEnum):
    received = "received"
    ignored = "ignored"
    triaged = "triaged"
    skipped = "skipped"
    needs_info = "needs_info"
    queued = "queued"
    claimed = "claimed"
    cloning = "cloning"
    agent_running = "agent_running"
    done = "done"
    commented = "commented"
    failed = "failed"
    # Legacy berth path; unused by the pull queue.
    berthing = "berthing"
    running = "running"


IN_FLIGHT = {
    RunStatus.claimed,
    RunStatus.cloning,
    RunStatus.agent_running,
    RunStatus.running,
}

QUEUED_OR_IN_FLIGHT = {RunStatus.queued, *IN_FLIGHT}


class IssueRef(BaseModel):
    platform: Platform
    owner: str
    repo: str
    number: int
    url: str = ""

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.owner}/{self.repo}#{self.number}"


class WorkspaceRef(BaseModel):
    id: str
    name: str
    template: str
    status: str = "pending"
    url: str = ""


class Run(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    issue: IssueRef
    status: RunStatus = RunStatus.received
    triage: TriageResult | None = None
    workspace: WorkspaceRef | None = None
    error: str = ""
    delivery_id: str = ""
    claimed_by: str = ""
    last_progress_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    extra: dict[str, Any] = Field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC)

    def commented_keys(self) -> list[str]:
        posted = self.extra.get("commented")
        if isinstance(posted, list):
            return [str(item) for item in posted]
        return []

    def mark_commented(self, key: str) -> None:
        posted = self.commented_keys()
        if key not in posted:
            posted.append(key)
        self.extra["commented"] = posted
