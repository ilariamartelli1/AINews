"""Summarizer plugin interface + registry.

To add a new engine:

    from .base import Summarizer, register

    @register("myengine")
    class MyEngine(Summarizer):
        def summarize(self, inp: SummaryInput) -> ArticleDraft: ...

The orchestrator never imports a concrete engine — it calls
``build_summarizer(config)`` and gets the engine named by ``config.type``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Type

from ..article import ArticleDraft
from ..config import SummarizerConfig


@dataclass
class RelatedItem:
    """A prior item surfaced by the comparison module, passed to the summarizer
    so it can write the 'how it compares' section."""

    title: str
    url: str
    similarity: float = 0.0
    summary: str = ""
    related_id: int | None = None      # archive item id, for the comparison link


@dataclass
class SummaryInput:
    """Everything a summarizer needs to produce one article."""

    title: str
    summary: str                       # feed summary (fallback text)
    source_text: str                   # full extracted page text (may be empty)
    url: str
    source_id: str = ""
    scope_name: str = ""
    scope_topics: list[str] = field(default_factory=list)
    related: list[RelatedItem] = field(default_factory=list)

    def best_text(self) -> str:
        """Prefer the full page text; fall back to the feed summary."""
        return self.source_text.strip() or self.summary.strip()


class Summarizer(ABC):
    type: str = "base"

    def __init__(self, config: SummarizerConfig) -> None:
        self.config = config

    @abstractmethod
    def summarize(self, inp: SummaryInput) -> ArticleDraft:
        """Produce a structured article draft. Sets title/what_changed/
        why_it_matters/comparison and engine/model; the orchestrator attaches
        sources, comparison links, and scope tags."""
        raise NotImplementedError


SUMMARIZER_REGISTRY: dict[str, Type[Summarizer]] = {}


def register(type_name: str) -> Callable[[Type[Summarizer]], Type[Summarizer]]:
    def deco(cls: Type[Summarizer]) -> Type[Summarizer]:
        cls.type = type_name
        SUMMARIZER_REGISTRY[type_name] = cls
        return cls

    return deco


def build_summarizer(config: SummarizerConfig) -> Summarizer:
    cls = SUMMARIZER_REGISTRY.get(config.type)
    if cls is None:
        raise ValueError(
            f"unknown summarizer type {config.type!r}; "
            f"known types: {sorted(SUMMARIZER_REGISTRY)}"
        )
    return cls(config)
