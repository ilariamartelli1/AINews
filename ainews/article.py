"""Article data models.

``ArticleDraft`` is the summarizer's structured output before persistence.
``Article`` is the persisted post plus its attached sources and comparison links —
the unit the website (a later sprint) will render and archive.

The schema is intentionally structured (``what_changed`` / ``why_it_matters`` /
``comparison`` kept separate) so the front-end can lay them out and so quality
checks can reason about each part, with ``body`` holding the assembled Markdown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SourceRef:
    """A source reference attached to an article (preserves provenance)."""

    url: str
    title: str = ""
    source_id: str = ""
    is_primary: bool = False


@dataclass
class ComparisonLink:
    """A link from this article to a related prior item ('vs previous')."""

    related_item_id: int | None
    related_title: str
    related_url: str
    similarity: float = 0.0
    note: str = ""


@dataclass
class ArticleDraft:
    """Structured summarizer output for one selected item."""

    title: str
    what_changed: str
    why_it_matters: str
    comparison: str = ""                       # prose 'vs previous tools/models' section
    body: str = ""                             # assembled Markdown (built if empty)
    scope_tags: list[str] = field(default_factory=list)
    sources: list[SourceRef] = field(default_factory=list)
    comparisons: list[ComparisonLink] = field(default_factory=list)

    # Provenance of the generation
    engine: str = ""                          # summarizer type that produced this
    model: str = ""                           # LLM model id, if any

    def assemble_body(self) -> str:
        """Build the Markdown body from the structured parts if not already set."""
        if self.body:
            return self.body
        parts = [f"# {self.title}", "", "**What changed**", "", self.what_changed]
        if self.why_it_matters:
            parts += ["", "**Why it matters**", "", self.why_it_matters]
        if self.comparison:
            parts += ["", "**How it compares**", "", self.comparison]
        self.body = "\n".join(parts).strip()
        return self.body


@dataclass
class Article:
    """A persisted article record (mirrors the ``articles`` table)."""

    item_id: int
    title: str
    what_changed: str
    why_it_matters: str
    comparison: str = ""
    body: str = ""
    scope_tags: list[str] = field(default_factory=list)
    engine: str = ""
    model: str = ""
    quality_status: str = "pending"           # pass | flagged | fail
    quality_issues: list[str] = field(default_factory=list)
    published: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    sources: list[SourceRef] = field(default_factory=list)
    comparisons: list[ComparisonLink] = field(default_factory=list)
    id: int | None = None

    @classmethod
    def from_draft(cls, item_id: int, draft: ArticleDraft) -> "Article":
        draft.assemble_body()
        return cls(
            item_id=item_id,
            title=draft.title,
            what_changed=draft.what_changed,
            why_it_matters=draft.why_it_matters,
            comparison=draft.comparison,
            body=draft.body,
            scope_tags=list(draft.scope_tags),
            engine=draft.engine,
            model=draft.model,
            sources=list(draft.sources),
            comparisons=list(draft.comparisons),
        )
