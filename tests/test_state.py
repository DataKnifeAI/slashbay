from __future__ import annotations

from pathlib import Path

from slashbay.state.models import IssueRef, Run, RunStatus
from slashbay.state.store import MemoryStore, SqliteStore, build_store


def _run() -> Run:
    return Run(
        issue=IssueRef(
            platform="github",
            owner="DataKnifeAI",
            repo="slashbay",
            number=9,
            url="https://github.com/DataKnifeAI/slashbay/issues/9",
        )
    )


def test_memory_roundtrip() -> None:
    store = MemoryStore()
    run = store.put(_run())
    loaded = store.get(run.id)
    assert loaded is not None
    assert loaded.issue.key == "github:DataKnifeAI/slashbay#9"
    assert store.count_active() == 1
    run.status = RunStatus.commented
    store.put(run)
    assert store.count_active() == 0


def test_sqlite_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "slashbay.db"
    store = SqliteStore(str(path))
    run = store.put(_run())
    other = SqliteStore(str(path))
    loaded = other.get(run.id)
    assert loaded is not None
    assert loaded.issue.number == 9


def test_build_store_memory() -> None:
    assert isinstance(build_store("memory://"), MemoryStore)
