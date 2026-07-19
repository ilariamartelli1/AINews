"""Article generation orchestrator (Sprint 2).

For each relevant, not-yet-written item in the archive:

    fetch full page (cache) -> find related priors (TF-IDF) -> summarize
      (Claude, extractive fallback) -> quality-check -> persist article
      + sources + comparison links

The LLM engine is used when configured; any per-item LLM failure falls back to
the zero-cost extractive engine so a bad key or rate limit never blocks the run.
Sources are always attached (transparency), and articles that fail quality checks
are still stored (flagged) but marked not-publishable for a later sprint's
publication gate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .article import Article, SourceRef, ComparisonLink
from .compare import find_related
from .config import ScopeConfig, SummarizerConfig
from .content import fetch_page
from .quality import check_article
from .relevance import _matches  # reuse the word-boundary keyword matcher
from .store import Store
from .summarize import build_summarizer, SummaryInput
from .summarize.base import Summarizer

log = logging.getLogger("ainews.generate")


@dataclass
class GenerationReport:
    considered: int = 0
    generated: int = 0
    passed: int = 0
    flagged: int = 0
    failed_quality: int = 0
    llm_fallbacks: int = 0
    content_fetched: int = 0
    errors: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "generated": self.generated,
            "passed": self.passed,
            "flagged": self.flagged,
            "failed_quality": self.failed_quality,
            "llm_fallbacks": self.llm_fallbacks,
            "content_fetched": self.content_fetched,
            "errors": self.errors,
        }


def _scope_tags(scope: ScopeConfig, item: dict) -> list[str]:
    text = f"{item.get('title', '')}\n{item.get('summary', '')}".lower()
    tags = [scope.name] if scope.name else []
    tags += _matches(text, scope._strong_lc)[:5]
    return tags


def _summarize_with_fallback(
    primary: Summarizer,
    fallback: Summarizer,
    inp: SummaryInput,
    report: GenerationReport,
    item_url: str,
):
    """Try the configured engine; fall back to extractive on any failure."""
    try:
        return primary.summarize(inp)
    except Exception as exc:
        if primary is fallback:
            raise
        report.llm_fallbacks += 1
        log.warning("summarizer failed for %s (%s); using extractive fallback",
                    item_url, exc)
        return fallback.summarize(inp)


def generate(
    scope: ScopeConfig,
    sconfig: SummarizerConfig,
    store: Store,
    limit: int = 20,
) -> GenerationReport:
    """Generate articles for up to ``limit`` relevant, unwritten items."""
    report = GenerationReport()

    primary = build_summarizer(sconfig)
    fallback = (
        primary if sconfig.type == "extractive"
        else build_summarizer(SummarizerConfig(type="extractive"))
    )

    items = store.relevant_without_article(limit=limit)
    report.considered = len(items)

    for item in items:
        item_id = item["id"]
        url = item["url"]
        try:
            # 1. Full-page content (cache once).
            source_text = item.get("content") or ""
            if sconfig.fetch_full_page and not source_text:
                fetched = fetch_page(url)
                if fetched:
                    source_text = fetched
                    store.set_item_content(item["url_fingerprint"], fetched)
                    report.content_fetched += 1

            # 2. Related prior items (comparative context).
            priors = store.prior_items_for_compare(exclude_item_id=item_id)
            related = find_related(
                item, priors,
                top_k=sconfig.compare_top_k,
                min_similarity=sconfig.compare_min_similarity,
            )

            # 3. Summarize.
            inp = SummaryInput(
                title=item["title"],
                summary=item.get("summary", ""),
                source_text=source_text,
                url=url,
                source_id=item.get("source_id", ""),
                scope_name=scope.name,
                scope_topics=list(scope.topics),
                related=related,
            )
            draft = _summarize_with_fallback(primary, fallback, inp, report, url)

            # 4. Attach provenance + comparison links + scope tags.
            draft.scope_tags = _scope_tags(scope, item)
            draft.sources = [SourceRef(
                url=url, title=item["title"], source_id=item.get("source_id", ""),
                is_primary=True,
            )]
            draft.comparisons = [
                ComparisonLink(
                    related_item_id=r.related_id,
                    related_title=r.title,
                    related_url=r.url,
                    similarity=r.similarity,
                )
                for r in related
            ]

            # 5. Quality checks (comparison only required when priors existed).
            qr = check_article(
                draft,
                min_words=sconfig.min_words,
                max_words=sconfig.max_words,
                require_comparison=bool(related),
            )

            # 6. Persist (store even flagged/failed for audit; publish gate later).
            article = Article.from_draft(item_id, draft)
            article.quality_status = qr.status
            article.quality_issues = qr.issues
            store.insert_article(article)

            report.generated += 1
            if qr.status == "pass":
                report.passed += 1
            elif qr.status == "flagged":
                report.flagged += 1
            else:
                report.failed_quality += 1
            log.info("article for item %d: %s (%s)", item_id, qr.status,
                     ", ".join(qr.issues) or "clean")

        except Exception as exc:
            report.errors[str(item_id)] = f"{type(exc).__name__}: {exc}"
            log.warning("failed to generate article for item %d (%s): %s",
                        item_id, url, exc)

    return report


def generate_from_paths(
    scope_path: str | Path,
    summarizer_path: str | Path,
    db_path: str | Path,
    limit: int = 20,
) -> GenerationReport:
    scope = ScopeConfig.load(scope_path)
    sconfig = SummarizerConfig.load(summarizer_path)
    with Store(db_path) as store:
        return generate(scope, sconfig, store, limit=limit)
