"""Pre-publication quality checks.

Runs a set of cheap, deterministic checks over a generated article and returns a
verdict. Two severities:

- **fail**  : the article should not be published as-is (empty body, missing
  sources, too short, obvious placeholder/refusal text).
- **flag**  : publishable but worth review (too long, missing comparison, thin
  "why it matters").

The orchestrator records the status + issues on the article so a later
publication step can gate on them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .article import ArticleDraft

_WORD = re.compile(r"\b\w+\b")

# Phrases that indicate the summarizer failed to produce real content.
_PLACEHOLDER_MARKERS = (
    "i cannot", "i can't", "as an ai", "i'm sorry", "i am sorry",
    "unable to summarize", "no content", "lorem ipsum",
)


@dataclass
class QualityReport:
    status: str                         # pass | flagged | fail
    issues: list[str] = field(default_factory=list)

    @property
    def ok_to_publish(self) -> bool:
        return self.status != "fail"


def _word_count(text: str) -> int:
    return len(_WORD.findall(text))


def check_article(
    draft: ArticleDraft,
    *,
    min_words: int = 40,
    max_words: int = 320,
    require_comparison: bool = False,
) -> QualityReport:
    """Evaluate a draft. ``require_comparison`` is typically False (comparison is
    only expected when related prior items exist — the orchestrator decides)."""
    body = draft.assemble_body()
    issues: list[str] = []
    fail = False

    # --- Sources (transparency requirement) ---
    if not draft.sources:
        issues.append("missing sources")
        fail = True

    # --- Core content present ---
    if not draft.what_changed.strip():
        issues.append("empty 'what changed'")
        fail = True
    if not draft.why_it_matters.strip():
        issues.append("empty 'why it matters'")

    # --- Length ---
    wc = _word_count(body)
    if wc < min_words:
        issues.append(f"too short ({wc} words < {min_words})")
        fail = True
    elif wc > max_words:
        issues.append(f"too long ({wc} words > {max_words})")

    # --- Placeholder / refusal / clarity ---
    low = body.lower()
    for marker in _PLACEHOLDER_MARKERS:
        if marker in low:
            issues.append(f"placeholder/refusal text: {marker!r}")
            fail = True
            break

    # --- Title sanity ---
    if not draft.title.strip():
        issues.append("empty title")
        fail = True

    # --- Comparison (soft) ---
    if require_comparison and not draft.comparison.strip():
        issues.append("missing comparison section")

    if fail:
        status = "fail"
    elif issues:
        status = "flagged"
    else:
        status = "pass"
    return QualityReport(status=status, issues=issues)
