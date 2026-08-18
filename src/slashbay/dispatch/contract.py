"""Dispatch contract: job payload tells a warm dkai-agent to run `agent -p`.

Slashbay is the queue. Warm workspaces already running in Coder pull jobs.
Do not start `agent worker` for issue dispatch — prompt mode only:

    agent -p "$SLASHBAY_PROMPT"

Concurrency is the number of warm `dkai-agent` pullers (2–5), not per-issue
berths. Cursor CLI is the coding worker on one named human seat
(`dataknife-coder-issue-bot`). Do not share one Pro key across a farm;
do not create dummy bot seats. The pull token is a pool secret
(`SLASHBAY_WORKER_TOKEN`), not a Cursor account.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from slashbay.config import Settings
from slashbay.webhooks.events import IssueEvent


class DispatchPlan(BaseModel):
    """Everything a puller needs to run `agent -p` on a claimed job."""

    workspace_name: str = ""
    template: str = "dkai-agent"
    git_url: str
    command: list[str]
    env: dict[str, str] = Field(default_factory=dict)
    rich_parameters: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


def prompt_for_issue(issue: IssueEvent) -> str:
    return (
        f"Work this {issue.platform} issue in {issue.full_name}.\n"
        f"Issue: {issue.url}\n"
        f"Title: {issue.title}\n\n"
        f"{issue.body}\n\n"
        "Stay inside this repository. Open a focused change, test what you can, "
        "and comment the result back on the issue. Do not invent secrets."
    )


def build_dispatch_plan(
    issue: IssueEvent,
    *,
    run_id: str,
    workspace_name: str,
    settings: Settings,
) -> DispatchPlan:
    git_url = settings.workspace_git_url or issue.clone_url
    prompt = prompt_for_issue(issue)
    env = {
        "SLASHBAY_DISPATCH": "1",
        "SLASHBAY_RUN_ID": run_id,
        "SLASHBAY_ISSUE_URL": issue.url,
        "SLASHBAY_PROMPT": prompt,
        "CURSOR_WORKER_DIR": "/home/coder/agent-workspace",
    }
    rich: dict[str, str] = {}
    if settings.cursor_api_key:
        rich["cursor_api_key"] = settings.cursor_api_key
    if git_url:
        rich["cursor_worker_git_url"] = git_url
    command = ["agent", "-p", prompt]
    return DispatchPlan(
        workspace_name=workspace_name,
        template=settings.coder_template,
        git_url=git_url,
        command=command,
        env=env,
        rich_parameters=rich,
        notes=(
            "Warm dkai-agent pullers claim this job and run `agent -p`. "
            "Slashbay does not create workspaces or start `agent worker`. "
            "Key belongs to one paid human seat (dataknife-coder-issue-bot)."
        ),
    )
