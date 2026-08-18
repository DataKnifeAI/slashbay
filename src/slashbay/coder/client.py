"""Coder HTTP client for list/health of warm dkai-agent workspaces.

Required env (see `.env.example`) when capacity listing is enabled:
- CODER_ACCESS_URL  e.g. https://coder.dataknife.net
- CODER_TOKEN       session / API token with permission to list workspaces

Herald does **not** create or start workspaces. Warm `dkai-agent` workspaces
pull jobs from Slashbay. This client is optional GET-only capacity.

This module talks to Coder's API. It does not vendor templates or start a
Cursor worker pool.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from slashbay.config import Settings

log = logging.getLogger(__name__)

_NAME_SAFE = re.compile(r"[^a-z0-9-]+")


class CoderError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkspaceInfo:
    id: str
    name: str
    template: str
    status: str
    url: str
    raw: dict[str, Any]


# Back-compat alias for imports that still say CreatedWorkspace.
CreatedWorkspace = WorkspaceInfo


def workspace_name(owner: str, repo: str, number: int, run_id: str) -> str:
    slug = _NAME_SAFE.sub("-", f"sb-{owner}-{repo}-{number}-{run_id[:8]}".lower()).strip("-")
    return slug[:32].strip("-") or f"sb-{run_id[:8]}"


class CoderClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._owns_client = client is None
        base = settings.coder_access_url.rstrip("/")
        headers = {"Coder-Session-Token": settings.coder_token}
        self._client = client or httpx.AsyncClient(base_url=base, headers=headers, timeout=30.0)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def health(self) -> bool:
        response = await self._client.get("/api/v2/buildinfo")
        if response.status_code >= 400:
            raise CoderError(f"coder health failed: {response.status_code} {response.text}")
        return True

    async def list_workspaces(self) -> list[WorkspaceInfo]:
        owner = self._settings.coder_workspace_owner or "me"
        response = await self._client.get(f"/api/v2/users/{owner}/workspaces")
        if response.status_code >= 400:
            raise CoderError(f"list workspaces failed: {response.status_code} {response.text}")
        data = response.json()
        items = data
        if isinstance(data, dict):
            items = data.get("workspaces") or data.get("items") or []
        return [self._to_workspace(item) for item in items if isinstance(item, dict)]

    def _to_workspace(self, data: dict[str, Any]) -> WorkspaceInfo:
        workspace_id = str(data.get("id") or "")
        name = str(data.get("name") or "")
        latest = data.get("latest_build") or {}
        status = str(latest.get("status") or data.get("status") or "pending")
        template = str(
            data.get("template_name") or data.get("template") or self._settings.coder_template
        )
        base = self._settings.coder_access_url.rstrip("/")
        url = f"{base}/@{self._settings.coder_workspace_owner}/{name}" if name else base
        return WorkspaceInfo(
            id=workspace_id,
            name=name,
            template=template,
            status=status,
            url=url,
            raw=data,
        )
