"""Source plugin interface + registry.

To add a new kind of source (API, scraper, ...):

    from .base import Source, register

    @register("myapi")
    class MyApiSource(Source):
        def fetch(self) -> list[RawItem]:
            ...

The pipeline never imports concrete sources directly — it calls
``build_source(cfg)`` and gets back the right plugin for ``cfg.type``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Type

from ..config import SourceConfig
from ..models import RawItem


class Source(ABC):
    """Base class for all discovery sources."""

    #: registry key; set by @register
    type: str = "base"

    def __init__(self, config: SourceConfig) -> None:
        self.config = config
        self.id = config.id
        self.weight = config.weight
        self.options = config.options

    @abstractmethod
    def fetch(self) -> list[RawItem]:
        """Fetch current candidate items. Must not raise on individual bad
        entries — skip them and return what parsed cleanly. May raise on a
        total failure (network/parse); the pipeline catches per-source errors."""
        raise NotImplementedError


SOURCE_REGISTRY: dict[str, Type[Source]] = {}


def register(type_name: str) -> Callable[[Type[Source]], Type[Source]]:
    """Class decorator that registers a Source subclass under ``type_name``."""

    def deco(cls: Type[Source]) -> Type[Source]:
        cls.type = type_name
        SOURCE_REGISTRY[type_name] = cls
        return cls

    return deco


def build_source(config: SourceConfig) -> Source:
    """Instantiate the plugin registered for ``config.type``."""
    cls = SOURCE_REGISTRY.get(config.type)
    if cls is None:
        raise ValueError(
            f"unknown source type {config.type!r} for source {config.id!r}; "
            f"known types: {sorted(SOURCE_REGISTRY)}"
        )
    return cls(config)
