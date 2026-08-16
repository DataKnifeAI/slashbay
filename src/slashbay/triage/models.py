from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TriageAction(StrEnum):
    actionable = "actionable"
    needs_info = "needs_info"
    skip = "skip"


class TriageResult(BaseModel):
    action: TriageAction
    start_workspace: bool
    comment: str
    confidence: float = Field(ge=0.0, le=1.0)
    model: str = ""

    @field_validator("start_workspace")
    @classmethod
    def workspace_only_when_actionable(cls, value: bool, info: Any) -> bool:
        action = info.data.get("action")
        if action != TriageAction.actionable:
            return False
        return value


def parse_triage_payload(data: dict[str, Any]) -> TriageResult:
    """Validate an LLM (or heuristic) JSON object into the dispatch contract."""
    return TriageResult.model_validate(data)
