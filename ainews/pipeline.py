"""Daily discovery pipeline orchestrator.

Ties the Sprint-1 stages together:

    fetch (pluggable sources)
      -> dedupe (within-batch + cross-run archive)
        -> relevance/novelty scoring (against active scope)
          -> persist raw items + metadata + verdicts (durable archive)

Designed to run unattended once per day. Per-source failures are isolated so one
dead feed never sinks the run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import ScopeConfig, SourceConfig, load_sources
from .dedup import dedupe
from .models import RawItem
from .relevance import apply_relevance
from .sources import build_source
from .store import Store

log = logging.getLogger("ainews.pipeline")


@dataclass
class RunReport:
    fetched: int = 0
    per_source: dict[str, int] = field(default_factory=dict)
    source_errors: dict[str, str] = field(default_factory=dict)
    duplicates: int = 0
    unique: int = 0
    relevant: int = 0
    irrelevant: int = 0
    inserted: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "fetched": self.fetched,
            "per_source": self.per_source,
            "source_errors": self.source_errors,
            "duplicates": self.duplicates,
            "unique": self.unique,
            "relevant": self.relevant,
            "irrelevant": self.irrelevant,
            "inserted": self.inserted,
        }


def fetch_all(source_configs: list[SourceConfig]) -> tuple[list[RawItem], RunReport]:
    """Fetch from every enabled source, isolating per-source failures."""
    report = RunReport()
    items: list[RawItem] = []
    for cfg in source_configs:
        if not cfg.enabled:
            continue
        try:
            source = build_source(cfg)
            fetched = source.fetch()
            items.extend(fetched)
            report.per_source[cfg.id] = len(fetched)
            log.info("source %s: %d items", cfg.id, len(fetched))
        except Exception as exc:  # isolate: one bad feed must not kill the run
            report.source_errors[cfg.id] = f"{type(exc).__name__}: {exc}"
            log.warning("source %s failed: %s", cfg.id, exc)
    report.fetched = len(items)
    return items, report


def run(
    scope: ScopeConfig,
    source_configs: list[SourceConfig],
    store: Store,
) -> RunReport:
    """Execute one full discovery run and persist results."""
    run_id = store.start_run()

    items, report = fetch_all(source_configs)

    # Dedup (within-batch + against the persisted archive).
    dd = dedupe(items, store)
    report.duplicates = len(dd.duplicates)
    report.unique = len(dd.unique)

    # Relevance / novelty scoring on the surviving unique items.
    for item in dd.unique:
        apply_relevance(item, scope)
    report.relevant = sum(1 for i in dd.unique if i.status == "relevant")
    report.irrelevant = sum(1 for i in dd.unique if i.status == "irrelevant")

    # Persist everything for the archive: unique items (with verdict) plus the
    # dropped duplicates (flagged), so the run is fully auditable later.
    report.inserted = store.insert_items(dd.unique + dd.duplicates)

    store.finish_run(run_id, report.as_dict())
    log.info(
        "run done: fetched=%d unique=%d relevant=%d duplicates=%d inserted=%d",
        report.fetched, report.unique, report.relevant, report.duplicates, report.inserted,
    )
    return report


def run_from_paths(
    scope_path: str | Path,
    sources_path: str | Path,
    db_path: str | Path,
) -> RunReport:
    """Convenience entry: load config from disk, open the store, run once."""
    scope = ScopeConfig.load(scope_path)
    source_configs = load_sources(sources_path)
    with Store(db_path) as store:
        return run(scope, source_configs, store)
