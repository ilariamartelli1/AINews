"""Core data models shared across the discovery pipeline.

A ``RawItem`` is a single candidate news item as fetched from a source, before
any relevance/dedup decision is made. It carries the fingerprints used for
deduplication and the fields needed by later pipeline stages (summarization,
publication, archive).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


# Query params that are tracking noise and must not affect item identity.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_reader", "utm_name", "utm_brand", "utm_social",
    "gclid", "fbclid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src",
    "source", "cmpid", "spm", "at_medium", "at_campaign",
}

_WS_RE = re.compile(r"\s+")
_NONWORD_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_url(url: str) -> str:
    """Canonicalize a URL for identity comparison.

    Lowercases scheme/host, drops fragments, strips tracking query params,
    sorts remaining params, and removes a trailing slash. Returns the input
    unchanged if it cannot be parsed.
    """
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path.rstrip("/") or "/"
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
            if k.lower() not in _TRACKING_PARAMS]
    kept.sort()
    query = urlencode(kept)
    return urlunsplit((scheme, netloc, path, query, ""))


def normalize_title(title: str) -> str:
    """Reduce a title to a comparable core: lowercase, punctuation-stripped,
    whitespace-collapsed. Used to build the title fingerprint for dedup."""
    if not title:
        return ""
    t = title.lower()
    t = _NONWORD_RE.sub(" ", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


@dataclass
class RawItem:
    """A single candidate item fetched from a source."""

    # Provenance
    source_id: str                      # which configured source produced this
    url: str                            # original item URL
    title: str
    summary: str = ""                   # feed summary / description (may be HTML-stripped upstream)
    author: str = ""
    published_at: str | None = None     # ISO-8601 string if known
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Extra source-specific metadata (tags, feed title, raw entry bits, etc.)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Filtering results (populated by later stages; defaults keep RawItem usable standalone)
    relevance_score: float = 0.0
    relevance_reasons: list[str] = field(default_factory=list)
    status: str = "new"                 # new | relevant | irrelevant | duplicate

    # --- Derived identity -------------------------------------------------
    @property
    def normalized_url(self) -> str:
        return normalize_url(self.url)

    @property
    def normalized_title(self) -> str:
        return normalize_title(self.title)

    @property
    def url_fingerprint(self) -> str:
        """Stable hash of the canonical URL — primary dedup key."""
        return _sha1(self.normalized_url)

    @property
    def title_fingerprint(self) -> str:
        """Stable hash of the normalized title — secondary dedup key that
        catches the same story republished under a different URL."""
        return _sha1(self.normalized_title)

    def text_for_scoring(self) -> str:
        """Concatenated lowercased text used by the relevance module."""
        return f"{self.title}\n{self.summary}".lower()

    def to_row(self) -> dict[str, Any]:
        """Flatten to a dict suitable for the store (metadata/reasons as JSON)."""
        d = asdict(self)
        return d
