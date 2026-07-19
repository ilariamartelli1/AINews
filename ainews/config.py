"""Editorial scope + source configuration models.

The scope config is the single knob that lets the whole product be retargeted
to a different AI niche (PRD "Scope configuration" / "Success condition") without
touching pipeline code. Everything the relevance module needs lives here, loaded
from a human-editable YAML file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# --------------------------------------------------------------------------
# Scope
# --------------------------------------------------------------------------
@dataclass
class ScoringWeights:
    """Tunable weights for the rule-based relevance/novelty scorer."""

    strong_keyword: float = 3.0
    normal_keyword: float = 1.0
    announcement_signal: float = 2.0    # novelty booster ("launches", "introduces", ...)
    exclude_penalty: float = 4.0        # per generic-commentary hit
    source_weight_scale: float = 1.0    # multiplies the per-source trust weight
    min_score: float = 3.0              # items scoring below this are dropped

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "ScoringWeights":
        d = d or {}
        known = {f: d[f] for f in cls.__dataclass_fields__ if f in d}
        return cls(**known)


@dataclass
class ScopeConfig:
    """The active editorial scope: what the blog is about and how to filter for it."""

    name: str
    description: str = ""
    topics: list[str] = field(default_factory=list)          # human-readable focus areas

    strong_keywords: list[str] = field(default_factory=list)  # high-signal terms
    normal_keywords: list[str] = field(default_factory=list)  # supporting terms
    announcement_signals: list[str] = field(default_factory=list)  # concrete-news markers
    exclude_keywords: list[str] = field(default_factory=list)  # generic-commentary / noise

    scoring: ScoringWeights = field(default_factory=ScoringWeights)

    # Lowercased lookups, built once in __post_init__.
    _strong_lc: list[str] = field(default_factory=list, repr=False)
    _normal_lc: list[str] = field(default_factory=list, repr=False)
    _signals_lc: list[str] = field(default_factory=list, repr=False)
    _exclude_lc: list[str] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._strong_lc = [k.lower() for k in self.strong_keywords]
        self._normal_lc = [k.lower() for k in self.normal_keywords]
        self._signals_lc = [k.lower() for k in self.announcement_signals]
        self._exclude_lc = [k.lower() for k in self.exclude_keywords]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ScopeConfig":
        if "name" not in d:
            raise ValueError("scope config must have a 'name'")
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            topics=list(d.get("topics", [])),
            strong_keywords=list(d.get("strong_keywords", [])),
            normal_keywords=list(d.get("normal_keywords", [])),
            announcement_signals=list(d.get("announcement_signals", [])),
            exclude_keywords=list(d.get("exclude_keywords", [])),
            scoring=ScoringWeights.from_dict(d.get("scoring")),
        )

    @classmethod
    def load(cls, path: str | Path) -> "ScopeConfig":
        path = Path(path)
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls.from_dict(data)


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------
@dataclass
class SourceConfig:
    """Configuration for one discovery source. ``type`` selects the plugin;
    ``options`` are passed through to that plugin's constructor."""

    id: str
    type: str                                    # e.g. "rss"
    enabled: bool = True
    weight: float = 1.0                          # source trust, feeds scoring
    options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SourceConfig":
        if "id" not in d or "type" not in d:
            raise ValueError("each source needs an 'id' and a 'type'")
        reserved = {"id", "type", "enabled", "weight", "options"}
        # Any extra top-level keys are treated as options for convenience.
        options = dict(d.get("options", {}))
        for k, v in d.items():
            if k not in reserved:
                options[k] = v
        return cls(
            id=d["id"],
            type=d["type"],
            enabled=bool(d.get("enabled", True)),
            weight=float(d.get("weight", 1.0)),
            options=options,
        )


def load_sources(path: str | Path) -> list[SourceConfig]:
    """Load the list of configured sources from YAML.

    Accepts either a top-level list or a mapping with a ``sources:`` key.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or []
    if isinstance(data, dict):
        data = data.get("sources", [])
    return [SourceConfig.from_dict(d) for d in data]
