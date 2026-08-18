from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ProgressStatus = Literal["claimed", "cloning", "agent_running", "mr_url", "failed"]


class JobView(BaseModel):
    """Body returned by GET /v1/jobs/claim."""

    id: str
    run_id: str
    prompt: str
    git_url: str
    issue_url: str
    command: list[str] = Field(default_factory=list)


class ProgressBody(BaseModel):
    status: ProgressStatus
    detail: str | None = None
    mr_url: str | None = None
    workspace: str | None = None


class CompleteBody(BaseModel):
    ok: bool
    summary: str | None = None
    mr_url: str | None = None
    error: str | None = None
