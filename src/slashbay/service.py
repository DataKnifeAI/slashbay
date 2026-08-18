from __future__ import annotations

import logging

from slashbay.config import Settings
from slashbay.jobs.queue import JobsQueue, issue_ref
from slashbay.state.models import Run, RunStatus
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

QUEUED_COMMENT = "queued for a warm workspace"


class Herald:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        triage: TriageProvider,
        publisher,
        queue: JobsQueue,
    ) -> None:
        self.settings = settings
        self.store = store
        self.triage = triage
        self.publisher = publisher
        self.queue = queue

    async def handle(self, issue: IssueEvent | None, *, delivery_id: str = "") -> Run | None:
        if issue is None:
            return None
        existing = self.queue.existing(delivery_id=delivery_id, issue_key=issue_ref(issue).key)
        if existing is not None:
            return existing

        run = Run(issue=issue_ref(issue), delivery_id=delivery_id)
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

        if result.action is TriageAction.skip:
            run.status = RunStatus.skipped
        elif result.action is TriageAction.needs_info:
            run.status = RunStatus.needs_info
        elif result.start_workspace or result.action is TriageAction.actionable:
            run = await self.queue.enqueue(run, issue)

        self.store.put(run)
        await self._publish(issue, run)
        return self.store.put(run)

    async def _publish(self, issue: IssueEvent, run: Run) -> None:
        if run.status is RunStatus.ignored:
            return
        if run.status is RunStatus.queued:
            comment = QUEUED_COMMENT
            if "queued" in run.commented_keys():
                return
        else:
            comment = (run.triage.comment if run.triage else "") or run.error
        if comment:
            await self.publisher.comment(issue, comment)
            if run.status is RunStatus.queued:
                run.mark_commented("queued")
        label = LABEL.get(run.triage.action) if run.triage else None
        if run.status is RunStatus.failed:
            label = "slashbay:failed"
        if label:
            await self.publisher.label(issue, [label])
        if run.status not in {
            RunStatus.failed,
            RunStatus.queued,
            RunStatus.claimed,
            RunStatus.cloning,
            RunStatus.agent_running,
            RunStatus.done,
        }:
            run.status = RunStatus.commented
