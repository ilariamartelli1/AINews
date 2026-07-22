"""Pipeline health evaluation + alert formatting.

Turns a daily run's report into a health verdict the ops layer acts on:

    ok         — pipeline ran and produced/updated content
    empty_news — pipeline ran cleanly but found nothing relevant AND wrote no
                 new article (a quiet-news day, or a broken source set)
    failure    — the pipeline raised, or every source errored

The GitHub Actions workflow reads this verdict (from ``data/last_run.json``) to
decide whether to open an alert issue; a ``failure`` also makes the CLI exit
non-zero so Actions' built-in failure email fires.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OK = "ok"
EMPTY = "empty_news"
FAILURE = "failure"


@dataclass
class Health:
    status: str                       # ok | empty_news | failure
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_failure(self) -> bool:
        return self.status == FAILURE

    @property
    def needs_alert(self) -> bool:
        return self.status in (FAILURE, EMPTY)

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "summary": self.summary, "details": self.details}


def evaluate(report: "DailyReport") -> Health:  # noqa: F821 (import cycle avoided)
    """Derive a Health verdict from a DailyReport."""
    d = report.as_dict()

    if not report.ok:
        return Health(FAILURE, f"pipeline failed: {report.error}", d)

    disc = report.discovery
    gen = report.generation

    # Every configured source erroring is a failure, not a quiet day.
    enabled_sources = disc.get("_enabled_sources") if isinstance(disc, dict) else None
    errored = len(disc.get("source_errors", {})) if isinstance(disc, dict) else 0
    fetched = disc.get("fetched", 0) if isinstance(disc, dict) else 0
    if fetched == 0 and errored > 0:
        return Health(FAILURE, f"all sources failed ({errored} errored, 0 items fetched)", d)

    relevant = disc.get("relevant", 0) if isinstance(disc, dict) else 0
    generated = gen.get("generated", 0) if isinstance(gen, dict) else 0
    if relevant == 0 and generated == 0:
        return Health(EMPTY, "no relevant news and no new articles today", d)

    return Health(
        OK,
        f"published/updated {generated} article(s) from {relevant} relevant item(s)",
        d,
    )


def format_alert(health: Health, *, repo_run_url: str = "") -> tuple[str, str]:
    """Return (issue_title, issue_body_markdown) for an alert."""
    if health.status == FAILURE:
        title = "🔴 AINews pipeline failure"
    else:
        title = "🟡 AINews: empty-news day (nothing published)"

    lines = [f"**{health.summary}**", ""]
    disc = health.details.get("discovery", {})
    gen = health.details.get("generation", {})
    if disc:
        lines += [
            "**Discovery**",
            f"- fetched: {disc.get('fetched')}",
            f"- relevant: {disc.get('relevant')}",
            f"- duplicates: {disc.get('duplicates')}",
            f"- source errors: {list(disc.get('source_errors', {}).keys()) or 'none'}",
            "",
        ]
    if gen:
        lines += [
            "**Generation**",
            f"- generated: {gen.get('generated')} (pass={gen.get('passed')}, "
            f"flagged={gen.get('flagged')}, fail={gen.get('failed_quality')})",
            f"- llm fallbacks: {gen.get('llm_fallbacks')}",
            "",
        ]
    if health.details.get("error"):
        lines += ["**Error**", "```", str(health.details["error"]), "```", ""]
    if repo_run_url:
        lines.append(f"[workflow run]({repo_run_url})")
    return title, "\n".join(lines)
