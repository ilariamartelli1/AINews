"""Rule-based relevance + novelty scoring.

Given the active :class:`~ainews.config.ScopeConfig`, score each item on how well
it matches the editorial scope and how much it looks like a concrete new
announcement (novelty) versus generic commentary. Zero-cost and deterministic;
an LLM relevance pass can be layered on top in a later sprint.

Scoring (all keyword matches are word-boundary aware, counted once each):

    score =  strong_hits   * strong_keyword_w
           + normal_hits   * normal_keyword_w
           + signal_hits   * announcement_signal_w      (novelty booster)
           - exclude_hits  * exclude_penalty            (generic-commentary drag)
           + source_weight * source_weight_scale

An item is **relevant** when its score clears ``min_score`` AND it shows at least
one in-scope signal (a strong keyword or an announcement signal). Items whose
only matches are exclude terms — pure commentary/noise — are always dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .config import ScopeConfig
from .models import RawItem


@dataclass
class RelevanceResult:
    score: float
    relevant: bool
    reasons: list[str]

    strong_hits: list[str]
    normal_hits: list[str]
    signal_hits: list[str]
    exclude_hits: list[str]


@lru_cache(maxsize=4096)
def _kw_pattern(keyword: str) -> re.Pattern:
    """Word-boundary matcher for a single keyword/phrase. Cached per keyword."""
    # \b works around alphanumerics; for phrases with spaces the outer \b anchors
    # the first/last word. Collapse internal whitespace to \s+ so "open  source"
    # still matches "open source".
    core = r"\s+".join(re.escape(part) for part in keyword.split())
    return re.compile(rf"\b{core}\b", re.IGNORECASE)


def _matches(text: str, keywords: list[str]) -> list[str]:
    return [kw for kw in keywords if _kw_pattern(kw).search(text)]


def score_item(item: RawItem, scope: ScopeConfig) -> RelevanceResult:
    """Score a single item against the scope. Pure — no I/O, no mutation."""
    text = item.text_for_scoring()
    w = scope.scoring

    strong = _matches(text, scope._strong_lc)
    normal = _matches(text, scope._normal_lc)
    signals = _matches(text, scope._signals_lc)
    excludes = _matches(text, scope._exclude_lc)

    source_weight = float(item.metadata.get("source_weight", 0.0))

    score = (
        len(strong) * w.strong_keyword
        + len(normal) * w.normal_keyword
        + len(signals) * w.announcement_signal
        - len(excludes) * w.exclude_penalty
        + source_weight * w.source_weight_scale
    )

    has_in_scope_signal = bool(strong or signals)
    relevant = score >= w.min_score and has_in_scope_signal

    reasons: list[str] = []
    if strong:
        reasons.append(f"strong: {', '.join(strong)}")
    if signals:
        reasons.append(f"novelty: {', '.join(signals)}")
    if normal:
        reasons.append(f"normal: {', '.join(normal)}")
    if excludes:
        reasons.append(f"excluded: {', '.join(excludes)}")
    if source_weight:
        reasons.append(f"source_weight: {source_weight}")
    if not has_in_scope_signal:
        reasons.append("no in-scope signal (dropped)")
    reasons.append(f"score={round(score, 2)} min={w.min_score}")

    return RelevanceResult(
        score=round(score, 3),
        relevant=relevant,
        reasons=reasons,
        strong_hits=strong,
        normal_hits=normal,
        signal_hits=signals,
        exclude_hits=excludes,
    )


def apply_relevance(item: RawItem, scope: ScopeConfig) -> RelevanceResult:
    """Score an item and write the verdict back onto it (score/reasons/status)."""
    result = score_item(item, scope)
    item.relevance_score = result.score
    item.relevance_reasons = result.reasons
    item.status = "relevant" if result.relevant else "irrelevant"
    return result
