from __future__ import annotations

import pytest
from pydantic import ValidationError

from slashbay.triage.models import TriageAction, parse_triage_payload
from slashbay.triage.providers import HeuristicTriage, OpenAITriage
from slashbay.webhooks.events import IssueEvent


def test_parse_actionable_schema() -> None:
    result = parse_triage_payload(
        {
            "action": "actionable",
            "start_workspace": True,
            "comment": "Berth a workspace.",
            "confidence": 0.81,
        }
    )
    assert result.action is TriageAction.actionable
    assert result.start_workspace is True
    assert result.confidence == 0.81


def test_parse_rejects_unknown_action() -> None:
    with pytest.raises(ValidationError):
        parse_triage_payload(
            {
                "action": "maybe",
                "start_workspace": False,
                "comment": "nope",
                "confidence": 0.5,
            }
        )


def test_parse_rejects_confidence_out_of_range() -> None:
    with pytest.raises(ValidationError):
        parse_triage_payload(
            {
                "action": "skip",
                "start_workspace": False,
                "comment": "nope",
                "confidence": 1.5,
            }
        )


def test_parse_forces_start_workspace_false_when_not_actionable() -> None:
    result = parse_triage_payload(
        {
            "action": "skip",
            "start_workspace": True,
            "comment": "should not start",
            "confidence": 0.9,
        }
    )
    assert result.start_workspace is False


@pytest.mark.asyncio
async def test_heuristic_needs_info_for_short_body() -> None:
    issue = IssueEvent(
        platform="github",
        action="opened",
        owner="DataKnifeAI",
        repo="slashbay",
        number=1,
        title="Bug",
        body="too short",
        url="https://example.com/1",
    )
    result = await HeuristicTriage().triage(issue)
    assert result.action is TriageAction.needs_info
    assert result.start_workspace is False


@pytest.mark.asyncio
async def test_openai_escalates_when_confidence_low(monkeypatch: pytest.MonkeyPatch) -> None:
    from slashbay.config import Settings

    calls: list[str] = []

    async def fake_complete(self: OpenAITriage, model: str, issue: IssueEvent):
        calls.append(model)
        if model == "gpt-5-nano":
            return parse_triage_payload(
                {
                    "action": "actionable",
                    "start_workspace": True,
                    "comment": "maybe",
                    "confidence": 0.4,
                    "model": model,
                }
            )
        return parse_triage_payload(
            {
                "action": "actionable",
                "start_workspace": True,
                "comment": "yes",
                "confidence": 0.88,
                "model": model,
            }
        )

    monkeypatch.setattr(OpenAITriage, "_complete", fake_complete)
    settings = Settings(openai_api_key="sk-test", triage_escalate_below=0.7)
    result = await OpenAITriage(settings).triage(
        IssueEvent(
            platform="github",
            action="opened",
            owner="DataKnifeAI",
            repo="slashbay",
            number=2,
            title="Real bug",
            body="enough detail " * 10,
            url="https://example.com/2",
        )
    )
    assert calls == ["gpt-5-nano", "gpt-5.6-luna"]
    assert result.model == "gpt-5.6-luna"
    assert result.confidence == 0.88
