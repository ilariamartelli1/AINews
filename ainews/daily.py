"""Daily pipeline orchestrator (Sprint 4).

One command runs the whole product end to end:

    discover → filter → dedupe   (pipeline.run)
      → summarize → compare       (generate.generate)
        → publish (static site)   (site.SiteBuilder)

Designed to be driven unattended by a scheduler (GitHub Actions cron). It never
raises out of ``run_daily`` — any failure is captured into the report so the ops
layer can alert and the caller can still commit the DB / exit with a code. A
health verdict (ok / empty_news / failure) and the full report are written to a
status file for the workflow to read.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import ScopeConfig, SummarizerConfig, load_sources
from .generate import generate as run_generate, GenerationReport
from .pipeline import run as run_pipeline, RunReport
from .site import SiteBuilder
from .store import Store

log = logging.getLogger("ainews.daily")

DEFAULT_STATUS_FILE = "data/last_run.json"


@dataclass
class DailyReport:
    ok: bool = True
    error: str | None = None
    discovery: dict[str, Any] = field(default_factory=dict)
    generation: dict[str, Any] = field(default_factory=dict)
    site: dict[str, Any] = field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error": self.error,
            "discovery": self.discovery,
            "generation": self.generation,
            "site": self.site,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def run_daily(
    scope: ScopeConfig,
    source_configs: list,
    sconfig: SummarizerConfig,
    store: Store,
    out_dir: str | Path,
    *,
    base_url: str = "",
    generate_limit: int = 50,
    now: str | None = None,
) -> DailyReport:
    """Run the full daily pipeline once. Captures failures into the report."""
    report = DailyReport(started_at=now)
    try:
        disc: RunReport = run_pipeline(scope, source_configs, store)
        report.discovery = disc.as_dict()

        gen: GenerationReport = run_generate(scope, sconfig, store, limit=generate_limit)
        report.generation = gen.as_dict()

        stats = SiteBuilder(store, scope=scope, base_url=base_url).build(out_dir)
        report.site = stats

        log.info("daily done: relevant=%d generated=%d posts=%d",
                 disc.relevant, gen.generated, stats.get("posts", 0))
    except Exception as exc:  # never propagate — let ops alert + caller decide exit
        report.ok = False
        report.error = f"{type(exc).__name__}: {exc}"
        log.exception("daily pipeline failed")
    report.finished_at = now
    return report


def write_status(report: DailyReport, health, path: str | Path = DEFAULT_STATUS_FILE) -> None:
    """Persist the report + health verdict for the ops layer to read."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"health": health.as_dict(), "report": report.as_dict()}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_daily_from_paths(
    scope_path: str | Path,
    sources_path: str | Path,
    summarizer_path: str | Path,
    db_path: str | Path,
    out_dir: str | Path,
    *,
    base_url: str = "",
    generate_limit: int = 50,
    now: str | None = None,
) -> DailyReport:
    scope = ScopeConfig.load(scope_path)
    sources = load_sources(sources_path)
    sconfig = SummarizerConfig.load(summarizer_path)
    with Store(db_path) as store:
        return run_daily(scope, sources, sconfig, store, out_dir,
                         base_url=base_url, generate_limit=generate_limit, now=now)
