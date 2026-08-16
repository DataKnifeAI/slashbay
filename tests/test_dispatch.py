from __future__ import annotations

from slashbay.config import Settings
from slashbay.dispatch.contract import build_dispatch_plan
from slashbay.webhooks.events import IssueEvent


def test_dispatch_plan_uses_agent_prompt_mode() -> None:
    issue = IssueEvent(
        platform="github",
        action="opened",
        owner="DataKnifeAI",
        repo="slashbay",
        number=4,
        title="Add healthz",
        body="Return JSON status ok.",
        url="https://github.com/DataKnifeAI/slashbay/issues/4",
        clone_url="https://github.com/DataKnifeAI/slashbay.git",
    )
    settings = Settings(cursor_api_key="sk-cursor-test", coder_template="dkai-agent")
    plan = build_dispatch_plan(issue, run_id="abc123", workspace_name="sb-test", settings=settings)
    assert plan.command[0:2] == ["agent", "-p"]
    assert "Add healthz" in plan.command[2]
    assert plan.template == "dkai-agent"
    assert plan.rich_parameters["cursor_api_key"] == "sk-cursor-test"
    assert plan.rich_parameters["cursor_worker_git_url"] == issue.clone_url
    assert plan.env["SLASHBAY_DISPATCH"] == "1"
    assert plan.env["SLASHBAY_RUN_ID"] == "abc123"
