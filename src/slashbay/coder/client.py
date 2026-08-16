"""Coder HTTP client for berthing a workspace from the dkai-agent template.

Required env (see `.env.example`):
- CODER_ACCESS_URL  e.g. https://coder.dataknife.net
- CODER_TOKEN       session / API token with permission to create workspaces
- CODER_TEMPLATE    template name, default `dkai-agent`
  (lives in DataKnifeAI/coder-templates — do not copy the template here)

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
class CreatedWorkspace:
    id: str
    name: str
    template: str
    status: str
    url: str
    raw: dict[str, Any]


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

    async def find_template_id(self, name: str | None = None) -> str:
        template = name or self._settings.coder_template
        response = await self._client.get("/api/v2/templates", params={"q": f"name:{template}"})
        if response.status_code >= 400:
            raise CoderError(f"list templates failed: {response.status_code} {response.text}")
        items = response.json()
        if isinstance(items, dict):
            items = items.get("templates") or items.get("items") or []
        for item in items:
            if item.get("name") == template:
                return str(item["id"])
        raise CoderError(f"template {template!r} not found at {self._settings.coder_access_url}")

    async def create_workspace(
        self,
        *,
        name: str,
        rich_parameters: dict[str, str],
        template_id: str | None = None,
    ) -> CreatedWorkspace:
        template_id = template_id or await self.find_template_id()
        owner = self._settings.coder_workspace_owner or "me"
        body: dict[str, Any] = {
            "name": name,
            "template_id": template_id,
            "rich_parameter_values": [
                {"name": key, "value": value} for key, value in rich_parameters.items()
            ],
        }
        response = await self._client.post(f"/api/v2/users/{owner}/workspaces", json=body)
        if response.status_code >= 400:
            raise CoderError(f"create workspace failed: {response.status_code} {response.text}")
        data = response.json()
        return self._to_workspace(data)

    async def start_workspace(self, workspace_id: str) -> CreatedWorkspace:
        response = await self._client.post(
            f"/api/v2/workspaces/{workspace_id}/builds",
            json={"transition": "start"},
        )
        if response.status_code >= 400:
            raise CoderError(f"start workspace failed: {response.status_code} {response.text}")
        data = response.json()
        workspace = data.get("workspace") or data
        return self._to_workspace(workspace)

    def _to_workspace(self, data: dict[str, Any]) -> CreatedWorkspace:
        workspace_id = str(data.get("id") or "")
        name = str(data.get("name") or "")
        latest = data.get("latest_build") or {}
        status = str(latest.get("status") or data.get("status") or "pending")
        base = self._settings.coder_access_url.rstrip("/")
        url = f"{base}/@{self._settings.coder_workspace_owner}/{name}" if name else base
        return CreatedWorkspace(
            id=workspace_id,
            name=name,
            template=self._settings.coder_template,
            status=status,
            url=url,
            raw=data,
        )
