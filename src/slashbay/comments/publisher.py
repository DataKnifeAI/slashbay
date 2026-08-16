from __future__ import annotations

import logging
from typing import Protocol

import httpx

from slashbay.config import Settings
from slashbay.webhooks.events import IssueEvent

log = logging.getLogger(__name__)


class IssuePublisher(Protocol):
    async def comment(self, issue: IssueEvent, body: str) -> None: ...
    async def label(self, issue: IssueEvent, labels: list[str]) -> None: ...


class NullPublisher:
    async def comment(self, issue: IssueEvent, body: str) -> None:
        log.info("dry-run comment %s: %s", issue.url, body[:200])

    async def label(self, issue: IssueEvent, labels: list[str]) -> None:
        log.info("dry-run labels %s: %s", issue.url, labels)


class GitHubPublisher:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._owns = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.github_api_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {settings.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=20.0,
        )

    async def aclose(self) -> None:
        if self._owns:
            await self._client.aclose()

    async def comment(self, issue: IssueEvent, body: str) -> None:
        path = f"/repos/{issue.owner}/{issue.repo}/issues/{issue.number}/comments"
        response = await self._client.post(path, json={"body": body})
        response.raise_for_status()

    async def label(self, issue: IssueEvent, labels: list[str]) -> None:
        path = f"/repos/{issue.owner}/{issue.repo}/issues/{issue.number}/labels"
        response = await self._client.post(path, json={"labels": labels})
        response.raise_for_status()


class GitLabPublisher:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._owns = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.gitlab_api_url.rstrip("/"),
            headers={"PRIVATE-TOKEN": settings.gitlab_token},
            timeout=20.0,
        )

    async def aclose(self) -> None:
        if self._owns:
            await self._client.aclose()

    async def comment(self, issue: IssueEvent, body: str) -> None:
        project = issue.project_id or f"{issue.owner}%2F{issue.repo}"
        path = f"/projects/{project}/issues/{issue.number}/notes"
        response = await self._client.post(path, json={"body": body})
        response.raise_for_status()

    async def label(self, issue: IssueEvent, labels: list[str]) -> None:
        project = issue.project_id or f"{issue.owner}%2F{issue.repo}"
        path = f"/projects/{project}/issues/{issue.number}"
        response = await self._client.put(path, json={"add_labels": ",".join(labels)})
        response.raise_for_status()


class RoutingPublisher:
    def __init__(self, github: IssuePublisher, gitlab: IssuePublisher) -> None:
        self._github = github
        self._gitlab = gitlab

    async def comment(self, issue: IssueEvent, body: str) -> None:
        await self._for(issue).comment(issue, body)

    async def label(self, issue: IssueEvent, labels: list[str]) -> None:
        await self._for(issue).label(issue, labels)

    def _for(self, issue: IssueEvent) -> IssuePublisher:
        return self._github if issue.platform == "github" else self._gitlab


def build_publisher(settings: Settings) -> IssuePublisher:
    if settings.dry_run:
        return NullPublisher()
    github: IssuePublisher = (
        GitHubPublisher(settings) if settings.github_token else NullPublisher()
    )
    gitlab: IssuePublisher = (
        GitLabPublisher(settings) if settings.gitlab_token else NullPublisher()
    )
    return RoutingPublisher(github, gitlab)
