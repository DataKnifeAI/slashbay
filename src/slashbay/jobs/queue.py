from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from fastapi import HTTPException

from slashbay.coder.client import CoderClient, CoderError
from slashbay.config import Settings
from slashbay.dispatch.contract import DispatchPlan, build_dispatch_plan
from slashbay.jobs.models import CompleteBody, JobView, ProgressBody
from slashbay.state.models import IssueRef, Run, RunStatus, WorkspaceRef
from slashbay.state.store import Store
from slashbay.webhooks.events import IssueEvent

log = logging.getLogger(__name__)

_HEARTBEATS = {"cloning", "agent_running"}


def snapshot_issue(issue: IssueEvent) -> dict[str, object]:
    return {
        "action": issue.action,
        "title": issue.title,
        "body": issue.body,
        "labels": list(issue.labels),
        "clone_url": issue.clone_url,
        "project_id": issue.project_id,
    }


def issue_event_from_run(run: Run) -> IssueEvent:
    snap = run.extra.get("issue") if isinstance(run.extra.get("issue"), dict) else {}
    labels = snap.get("labels") or []
    return IssueEvent(
        platform=run.issue.platform,
        action=str(snap.get("action") or "opened"),
        owner=run.issue.owner,
        repo=run.issue.repo,
        number=run.issue.number,
        title=str(snap.get("title") or ""),
        body=str(snap.get("body") or ""),
        url=run.issue.url,
        labels=tuple(str(item) for item in labels),
        clone_url=str(snap.get("clone_url") or ""),
        project_id=str(snap.get("project_id") or ""),
    )


def job_view(run: Run) -> JobView:
    plan = DispatchPlan.model_validate(run.extra.get("dispatch") or {})
    return JobView(
        id=run.id,
        run_id=run.id,
        prompt=plan.env.get("SLASHBAY_PROMPT")
        or (plan.command[2] if len(plan.command) > 2 else ""),
        git_url=plan.git_url,
        issue_url=run.issue.url,
        command=plan.command,
    )


class JobsQueue:
    """In-process + DB serialized job queue. Safe with SQLite while replicas=1."""

    def __init__(
        self,
        settings: Settings,
        store: Store,
        publisher,
        coder: CoderClient | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.publisher = publisher
        self.coder = coder
        self._lock = threading.Lock()

    def existing(self, *, delivery_id: str, issue_key: str) -> Run | None:
        if delivery_id:
            found = self.store.get_by_delivery_id(delivery_id)
            if found is not None:
                return found
        return self.store.get_active_by_issue_key(issue_key)

    async def enqueue(self, run: Run, issue: IssueEvent) -> Run:
        with self._lock:
            existing = self.existing(delivery_id=run.delivery_id, issue_key=run.issue.key)
            if existing is not None and existing.id != run.id:
                return existing
            plan = build_dispatch_plan(
                issue, run_id=run.id, workspace_name="", settings=self.settings
            )
            run.extra["dispatch"] = plan.model_dump()
            run.extra["issue"] = snapshot_issue(issue)
            run.status = RunStatus.queued
            if self.store.count_active() > self.settings.max_concurrent:
                log.warning(
                    "queue depth above SLASHBAY_MAX_CONCURRENT=%s; still enqueueing",
                    self.settings.max_concurrent,
                )
            self.store.put(run)
        await self._maybe_log_coder_capacity()
        return run

    async def _maybe_log_coder_capacity(self) -> None:
        if self.coder is None:
            return
        try:
            workspaces = await self.coder.list_workspaces()
            log.info("coder workspaces visible=%s (capacity check only)", len(workspaces))
        except CoderError:
            log.warning("coder list/health failed; enqueue continues")

    async def claim(self, workspace: str) -> JobView | None:
        with self._lock:
            run = self.store.claim_next(workspace, self.settings.job_lease_seconds)
            if run is None:
                return None
            run.workspace = WorkspaceRef(
                id=workspace,
                name=workspace,
                template=self.settings.coder_template,
                status="claimed",
            )
            self.store.put(run)
        await self._comment_once(
            run,
            "claimed",
            f"claimed by {workspace}",
            labels=["slashbay:running"],
        )
        return job_view(run)

    async def progress(self, job_id: str, body: ProgressBody) -> Run:
        with self._lock:
            run = self._require(job_id)
            workspace = body.workspace or run.claimed_by
            if body.status == "failed":
                run.status = RunStatus.failed
                run.error = body.detail or "worker reported failed"
            elif body.status != "mr_url":
                run.status = RunStatus(body.status)
            if workspace:
                run.claimed_by = workspace
                run.workspace = WorkspaceRef(
                    id=workspace,
                    name=workspace,
                    template=self.settings.coder_template,
                    status=body.status,
                )
            if body.mr_url:
                run.extra["mr_url"] = body.mr_url
            run.last_progress_at = datetime.now(UTC)
            self.store.put(run)

        if body.status in _HEARTBEATS:
            return run
        if body.status == "claimed":
            name = workspace or run.claimed_by or "workspace"
            await self._comment_once(
                run, "claimed", f"claimed by {name}", labels=["slashbay:running"]
            )
            return run
        if body.status == "mr_url":
            url = body.mr_url or ""
            await self._comment_once(
                run, "mr_url", f"Merge request: {url}" if url else (body.detail or "")
            )
            return run
        if body.status == "failed":
            await self._comment_once(
                run,
                "failed",
                run.error or body.detail or "job failed",
                labels=["slashbay:failed"],
            )
        return run

    async def complete(self, job_id: str, body: CompleteBody) -> Run:
        with self._lock:
            run = self._require(job_id)
            if body.mr_url:
                run.extra["mr_url"] = body.mr_url
            if body.ok:
                run.status = RunStatus.done
                run.error = ""
            else:
                run.status = RunStatus.failed
                run.error = body.error or "job failed"
            run.last_progress_at = datetime.now(UTC)
            self.store.put(run)

        if body.ok:
            summary = body.summary or "done"
            extra = f"\n\n{body.mr_url}" if body.mr_url else ""
            await self._comment_once(run, "done", f"{summary}{extra}", labels=["slashbay:done"])
        else:
            await self._comment_once(
                run,
                "failed",
                body.error or run.error or "job failed",
                labels=["slashbay:failed"],
            )
        return run

    def _require(self, job_id: str) -> Run:
        run = self.store.get(job_id)
        if run is None:
            raise HTTPException(status_code=404, detail="job not found")
        return run

    async def _comment_once(
        self,
        run: Run,
        key: str,
        body: str,
        labels: list[str] | None = None,
    ) -> None:
        if key in run.commented_keys():
            return
        issue = issue_event_from_run(run)
        if body:
            await self.publisher.comment(issue, body)
        if labels:
            await self.publisher.label(issue, labels)
        run.mark_commented(key)
        self.store.put(run)


def issue_ref(issue: IssueEvent) -> IssueRef:
    return IssueRef(
        platform=issue.platform,
        owner=issue.owner,
        repo=issue.repo,
        number=issue.number,
        url=issue.url,
    )
