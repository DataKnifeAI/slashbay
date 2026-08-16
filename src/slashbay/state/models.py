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
    berthing = "berthing"
    running = "running"
    commented = "commented"
    failed = "failed"


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    extra: dict[str, Any] = Field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC)
