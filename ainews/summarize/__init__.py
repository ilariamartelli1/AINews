"""Pluggable article summarizers.

A summarizer turns one selected item (title + text + comparison context) into a
short structured article. Engines register via ``@register("type")`` and are
built from config by ``build_summarizer``.

    extractive : zero-cost, deterministic, offline
    llm        : Claude (Anthropic API)
"""

from .base import (
    Summarizer,
    SummaryInput,
    RelatedItem,
    register,
    build_summarizer,
    SUMMARIZER_REGISTRY,
)
from . import extractive  # noqa: F401  (registration side-effect)
from . import llm         # noqa: F401

__all__ = [
    "Summarizer", "SummaryInput", "RelatedItem",
    "register", "build_summarizer", "SUMMARIZER_REGISTRY",
]
