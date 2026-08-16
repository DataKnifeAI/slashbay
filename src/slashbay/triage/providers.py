from __future__ import annotations

import json
import logging
from typing import Protocol

from slashbay.config import Settings
from slashbay.triage.models import TriageResult, parse_triage_payload
from slashbay.webhooks.events import IssueEvent

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Slashbay, DataKnifeAI's issue-webhook herald.
Classify a GitHub or GitLab issue for internal automation only.

Return a single JSON object with exactly these keys:
- action: "actionable" | "needs_info" | "skip"
- start_workspace: boolean (true only when action is actionable and a coding workspace should start)
- comment: short markdown to post back on the issue
- confidence: number between 0 and 1

Rules:
- skip: spam, questions with no work, duplicates, or out of scope for a coding agent
- needs_info: plausible work but missing repro, acceptance criteria, or repo context
- actionable: a coding agent can start from the issue as written
- Do not invent secrets. Do not claim the work is finished.
"""


class TriageProvider(Protocol):
    async def triage(self, issue: IssueEvent) -> TriageResult: ...


class HeuristicTriage:
    """Deterministic fallback when OPENAI_API_KEY is unset (local / tests)."""

    async def triage(self, issue: IssueEvent) -> TriageResult:
        body = (issue.body or "").strip()
        title = (issue.title or "").strip()
        text = f"{title}\n{body}".lower()
        if not title:
            return parse_triage_payload(
                {
                    "action": "skip",
                    "start_workspace": False,
                    "comment": "Slashbay skipped this: empty title.",
                    "confidence": 0.95,
                    "model": "heuristic",
                }
            )
        if any(token in text for token in ("wontfix", "spam", "do not automate")):
            return parse_triage_payload(
                {
                    "action": "skip",
                    "start_workspace": False,
                    "comment": "Slashbay skipped this issue (heuristic).",
                    "confidence": 0.85,
                    "model": "heuristic",
                }
            )
        if len(body) < 40:
            return parse_triage_payload(
                {
                    "action": "needs_info",
                    "start_workspace": False,
                    "comment": (
                        "Slashbay needs more detail (repro or acceptance criteria) "
                        "before berthing a workspace."
                    ),
                    "confidence": 0.75,
                    "model": "heuristic",
                }
            )
        return parse_triage_payload(
            {
                "action": "actionable",
                "start_workspace": True,
                "comment": "Slashbay will berth a Coder workspace and dispatch a coding agent.",
                "confidence": 0.72,
                "model": "heuristic",
            }
        )


class OpenAITriage:
    """Cheap-LLM classifier. Nano first; escalate to luna when confidence is low."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def triage(self, issue: IssueEvent) -> TriageResult:
        first = await self._complete(self._settings.triage_model, issue)
        if first.confidence < self._settings.triage_escalate_below:
            log.info(
                "escalating triage to %s (confidence=%.2f < %.2f)",
                self._settings.triage_escalate_model,
                first.confidence,
                self._settings.triage_escalate_below,
            )
            return await self._complete(self._settings.triage_escalate_model, issue)
        return first

    async def _complete(self, model: str, issue: IssueEvent) -> TriageResult:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._settings.openai_api_key)
        user = (
            f"platform: {issue.platform}\n"
            f"repo: {issue.full_name}\n"
            f"number: {issue.number}\n"
            f"url: {issue.url}\n"
            f"title: {issue.title}\n"
            f"labels: {', '.join(issue.labels)}\n\n"
            f"{issue.body}"
        )
        response = await client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        data["model"] = model
        return parse_triage_payload(data)


def build_triage(settings: Settings) -> TriageProvider:
    if settings.openai_api_key:
        return OpenAITriage(settings)
    log.warning("OPENAI_API_KEY unset; using heuristic triage")
    return HeuristicTriage()
