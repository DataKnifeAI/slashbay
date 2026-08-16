from __future__ import annotations

import logging

from slashbay.coder.client import CoderClient, CoderError, workspace_name
from slashbay.config import Settings
from slashbay.dispatch.contract import DispatchPlan, build_dispatch_plan
from slashbay.state.models import IssueRef, Run, RunStatus, WorkspaceRef
from slashbay.state.store import Store
from slashbay.triage.models import TriageAction
from slashbay.triage.providers import TriageProvider
from slashbay.webhooks.events import IssueEvent, repo_allowed

log = logging.getLogger(__name__)

LABEL = {
    TriageAction.actionable: "slashbay:queued",
    TriageAction.needs_info: "slashbay:needs-info",
    TriageAction.skip: "slashbay:skipped",
}


class Herald:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        triage: TriageProvider,
        publisher,
        coder: CoderClient | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.triage = triage
        self.publisher = publisher
        self.coder = coder

    async def handle(self, issue: IssueEvent | None) -> Run | None:
        if issue is None:
            return None
        run = Run(
            issue=IssueRef(
                platform=issue.platform,
                owner=issue.owner,
                repo=issue.repo,
                number=issue.number,
                url=issue.url,
            )
        )
        if not repo_allowed(issue.full_name, self.settings.allowlist_patterns()):
            run.status = RunStatus.ignored
            run.error = f"repo {issue.full_name} not allowlisted"
            return self.store.put(run)
        if issue.action.lower() not in self.settings.trigger_event_set():
            run.status = RunStatus.ignored
            run.error = f"action {issue.action!r} not in trigger set"
            return self.store.put(run)
        required = self.settings.trigger_label.strip()
        if required and required not in issue.labels:
            run.status = RunStatus.ignored
            run.error = f"missing trigger label {required!r}"
            return self.store.put(run)

        result = await self.triage.triage(issue)
        run.triage = result
        run.status = RunStatus.triaged
        self.store.put(run)

        if result.action is TriageAction.skip:
            run.status = RunStatus.skipped
        elif result.action is TriageAction.needs_info:
            run.status = RunStatus.needs_info
        elif result.start_workspace:
            if self.store.count_active() > self.settings.max_concurrent:
                run.status = RunStatus.failed
                run.error = "max concurrent workspaces reached"
            else:
                run = await self._berth(run, issue)

        self.store.put(run)
        await self._publish(issue, run)
        return self.store.put(run)

    async def _berth(self, run: Run, issue: IssueEvent) -> Run:
        name = workspace_name(issue.owner, issue.repo, issue.number, run.id)
        plan: DispatchPlan = build_dispatch_plan(
            issue, run_id=run.id, workspace_name=name, settings=self.settings
        )
        run.extra["dispatch"] = plan.model_dump()
        if self.settings.dry_run or self.coder is None:
            run.status = RunStatus.running
            run.workspace = WorkspaceRef(
                id="dry-run",
                name=name,
                template=plan.template,
                status="dry-run",
            )
            return run
        run.status = RunStatus.berthing
        self.store.put(run)
        try:
            created = await self.coder.create_workspace(
                name=name, rich_parameters=plan.rich_parameters
            )
            started = await self.coder.start_workspace(created.id)
            run.workspace = WorkspaceRef(
                id=started.id or created.id,
                name=started.name or created.name,
                template=plan.template,
                status=started.status,
                url=started.url,
            )
            run.status = RunStatus.running
        except CoderError as exc:
            log.exception("coder berth failed")
            run.status = RunStatus.failed
            run.error = str(exc)
        return run

    async def _publish(self, issue: IssueEvent, run: Run) -> None:
        if run.status is RunStatus.ignored:
            return
        comment = (run.triage.comment if run.triage else "") or run.error
        if run.workspace and run.workspace.url:
            comment = f"{comment}\n\nWorkspace: {run.workspace.url}"
        if comment:
            await self.publisher.comment(issue, comment)
        label = LABEL.get(run.triage.action) if run.triage else None
        if run.status is RunStatus.failed:
            label = "slashbay:failed"
        if label:
            await self.publisher.label(issue, [label])
        if run.status not in {RunStatus.failed, RunStatus.berthing, RunStatus.running}:
            run.status = RunStatus.commented
