from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from slashbay.config import Platform


@dataclass(frozen=True)
class IssueEvent:
    platform: Platform
    action: str
    owner: str
    repo: str
    number: int
    title: str
    body: str
    url: str
    labels: tuple[str, ...] = ()
    clone_url: str = ""
    project_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


def repo_allowed(full_name: str, patterns: list[str]) -> bool:
    owner, _, name = full_name.partition("/")
    for pattern in patterns:
        if pattern == full_name:
            return True
        if pattern.endswith("/*") and pattern[:-2] == owner:
            return True
        if pattern == f"{owner}/{name}":
            return True
    return False


def parse_github_issue_event(payload: dict[str, Any]) -> IssueEvent | None:
    if payload.get("zen") and "hook_id" in payload:
        return None
    issue = payload.get("issue")
    repo = payload.get("repository")
    if not isinstance(issue, dict) or not isinstance(repo, dict):
        return None
    if issue.get("pull_request"):
        return None
    full = str(repo.get("full_name") or "")
    owner, _, name = full.partition("/")
    labels = tuple(
        str(item.get("name"))
        for item in (issue.get("labels") or [])
        if isinstance(item, dict) and item.get("name")
    )
    return IssueEvent(
        platform="github",
        action=str(payload.get("action") or ""),
        owner=owner,
        repo=name,
        number=int(issue["number"]),
        title=str(issue.get("title") or ""),
        body=str(issue.get("body") or ""),
        url=str(issue.get("html_url") or ""),
        labels=labels,
        clone_url=str(repo.get("clone_url") or repo.get("html_url") or ""),
        raw=payload,
    )


def _gitlab_clone_url(http_url: str) -> str:
    if not http_url:
        return ""
    return http_url if http_url.endswith(".git") else f"{http_url}.git"


_GITLAB_ACTIONS = {
    "open": "opened",
    "reopen": "reopened",
    "close": "closed",
    "update": "updated",
}


def parse_gitlab_issue_event(payload: dict[str, Any]) -> IssueEvent | None:
    kind = payload.get("object_kind") or payload.get("event_type")
    if kind != "issue":
        return None
    attrs = payload.get("object_attributes") or {}
    project = payload.get("project") or {}
    path = str(project.get("path_with_namespace") or "")
    owner, _, name = path.partition("/")
    raw_action = str(attrs.get("action") or "")
    labels = tuple(
        str(item.get("title"))
        for item in (payload.get("labels") or [])
        if isinstance(item, dict) and item.get("title")
    )
    http_url = str(project.get("http_url") or project.get("web_url") or "")
    return IssueEvent(
        platform="gitlab",
        action=_GITLAB_ACTIONS.get(raw_action, raw_action),
        owner=owner,
        repo=name,
        number=int(attrs.get("iid") or 0),
        title=str(attrs.get("title") or ""),
        body=str(attrs.get("description") or ""),
        url=str(attrs.get("url") or ""),
        labels=labels,
        clone_url=_gitlab_clone_url(http_url),
        project_id=str(project.get("id") or attrs.get("project_id") or ""),
        raw=payload,
    )
