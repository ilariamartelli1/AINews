"""Pluggable discovery sources.

A source is anything that can produce ``RawItem`` candidates: an RSS feed, a JSON
API, an HTML page scraper. New source types register themselves via
``@register("type")`` and are constructed from a ``SourceConfig`` by ``build_source``.
"""

from .base import Source, register, build_source, SOURCE_REGISTRY
from . import rss  # noqa: F401  (import for registration side-effect)

__all__ = ["Source", "register", "build_source", "SOURCE_REGISTRY"]
