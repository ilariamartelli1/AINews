"""Zero-cost extractive summarizer.

Pulls the most salient sentences from the source text for "what changed",
derives a short "why it matters" line, and lists related prior items for the
comparison section. Deterministic, offline, no API — the always-available
fallback and the default when no LLM key is configured.
"""

from __future__ import annotations

import re

from ..article import ArticleDraft
from .base import Summarizer, SummaryInput, register

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WS = re.compile(r"\s+")

_ANNOUNCE = (
    "launch", "launches", "launched", "introduc", "announc", "release", "released",
    "unveil", "now available", "debut", "rolls out", "rolling out", "general availability",
    "open source", "open-source", "ships", "adds", "new",
)


def _sentences(text: str) -> list[str]:
    text = _WS.sub(" ", text).strip()
    if not text:
        return []
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]


def _score_sentence(sentence: str, index: int) -> float:
    words = sentence.split()
    n = len(words)
    if n < 4 or n > 60:
        return -1.0  # too short/long to be a useful lead sentence
    score = 0.0
    score += max(0.0, 3.0 - index * 0.6)          # earlier sentences win
    low = sentence.lower()
    score += sum(1.5 for kw in _ANNOUNCE if kw in low)
    if 8 <= n <= 34:                               # prefer medium-length sentences
        score += 1.0
    return score


@register("extractive")
class ExtractiveSummarizer(Summarizer):
    def summarize(self, inp: SummaryInput) -> ArticleDraft:
        sentences = _sentences(inp.best_text())

        ranked = sorted(
            ((_score_sentence(s, i), i, s) for i, s in enumerate(sentences)),
            key=lambda t: (-t[0], t[1]),
        )
        picked = [s for score, _, s in ranked if score > 0][:3]
        # Restore original document order for readability.
        picked.sort(key=lambda s: sentences.index(s))

        what_changed = " ".join(picked) if picked else (inp.summary or inp.title)

        why = self._why_it_matters(inp)
        comparison = self._comparison(inp)

        draft = ArticleDraft(
            title=inp.title,
            what_changed=what_changed,
            why_it_matters=why,
            comparison=comparison,
            engine=self.type,
        )
        draft.assemble_body()
        return draft

    @staticmethod
    def _why_it_matters(inp: SummaryInput) -> str:
        focus = inp.scope_name or "the AI tooling space"
        return (
            f"A concrete addition to {focus}: it changes what's available to "
            f"builders today rather than being general commentary."
        )

    @staticmethod
    def _comparison(inp: SummaryInput) -> str:
        if not inp.related:
            return ""
        lines = ["Related prior coverage to compare against:"]
        for r in inp.related:
            lines.append(f"- {r.title}")
        return "\n".join(lines)
