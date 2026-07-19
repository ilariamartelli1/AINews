"""RSS/Atom source plugin.

Fetches a feed over HTTP (with a timeout + real User-Agent so feeds don't 403),
parses it with feedparser, and maps each entry to a ``RawItem``. Robust to
malformed entries: bad entries are skipped, not fatal.
"""

from __future__ import annotations

import re
from calendar import timegm
from datetime import datetime, timezone

import feedparser
import httpx

from ..models import RawItem
from .base import Source, register


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_USER_AGENT = (
    "Mozilla/5.0 (compatible; ainews-bot/0.1; +https://github.com/ilariamartelli1/AINews) "
    "python-httpx"
)


def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def _struct_to_iso(struct_time) -> str | None:
    """Convert a feedparser time.struct_time (UTC) to an ISO-8601 string."""
    if not struct_time:
        return None
    try:
        return datetime.fromtimestamp(timegm(struct_time), tz=timezone.utc).isoformat()
    except (OverflowError, ValueError, TypeError):
        return None


@register("rss")
class RssSource(Source):
    """A single RSS/Atom feed."""

    def fetch(self) -> list[RawItem]:
        url = self.options.get("url")
        if not url:
            raise ValueError(f"rss source {self.id!r} missing 'url' option")

        timeout = float(self.options.get("timeout", 20.0))
        resp = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"},
        )
        resp.raise_for_status()

        parsed = feedparser.parse(resp.content)
        feed_title = getattr(parsed.feed, "title", "") if getattr(parsed, "feed", None) else ""

        items: list[RawItem] = []
        for entry in getattr(parsed, "entries", []):
            item = self._entry_to_item(entry, feed_title)
            if item is not None:
                items.append(item)
        return items

    def _entry_to_item(self, entry, feed_title: str) -> RawItem | None:
        link = entry.get("link") or ""
        title = _strip_html(entry.get("title") or "")
        if not link or not title:
            return None  # skip unusable entries

        summary = _strip_html(
            entry.get("summary")
            or (entry.get("content", [{}])[0].get("value") if entry.get("content") else "")
            or ""
        )
        author = entry.get("author") or ""

        published = (
            _struct_to_iso(entry.get("published_parsed"))
            or _struct_to_iso(entry.get("updated_parsed"))
        )

        tags = [t.get("term") for t in entry.get("tags", []) if t.get("term")]

        return RawItem(
            source_id=self.id,
            url=link,
            title=title,
            summary=summary,
            author=author,
            published_at=published,
            metadata={
                "feed_title": feed_title,
                "tags": tags,
                "source_weight": self.weight,
                "guid": entry.get("id") or entry.get("guid") or "",
            },
        )
