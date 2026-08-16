"""Dispatch contract: how a dkai-agent workspace is told to run `agent -p`.

Slashbay is not a Cursor product and does not run a worker farm.

Coding happens inside a Coder workspace created from
`DataKnifeAI/coder-templates` template `dkai-agent`. That template already
installs the Cursor CLI (`agent`), injects `CURSOR_API_KEY` from the
`cursor_api_key` rich parameter, and can autostart `agent worker start`.

Issue dispatch uses **prompt mode**, not a pool of `agent worker` processes:

    agent -p "$SLASHBAY_PROMPT"

Delivery (workspace-side; do not fork coder-templates in this repo):

1. Preferred: after the Coder agent is connected, run via
   `coder ssh <workspace> -- agent -p ...` (or the Coder SSH API).
2. Optional template hook: if `SLASHBAY_DISPATCH=1` and
   `/tmp/slashbay-prompt.md` (or `$SLASHBAY_PROMPT`) is present, a startup
   script in `dkai-agent` may invoke `agent -p`. Request that hook in
   coder-templates if it is not there yet.

Concurrency: one named human Cursor seat (`dataknife-coder-issue-bot`),
2–5 concurrent jobs (`SLASHBAY_MAX_CONCURRENT`). Do not share one Pro key
across a farm; do not create dummy bot seats.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from slashbay.config import Settings
from slashbay.webhooks.events import IssueEvent


class DispatchPlan(BaseModel):
    """Everything the berth needs so a human or hook can run `agent -p`."""

    workspace_name: str
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
            "Run `agent -p` inside the dkai-agent workspace after it is Started. "
            "Cursor CLI is the coding worker; Slashbay only berths and dispatches. "
            "Key belongs to one paid human seat (dataknife-coder-issue-bot)."
        ),
    )
