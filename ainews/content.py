"""Full-page content extraction.

Feed summaries are often truncated, so before summarizing we fetch the source
page and extract the main article text with trafilatura (boilerplate stripped).
The result is cached back onto the item in the archive so a page is fetched at
most once. Failures are non-fatal — the caller falls back to the feed summary.
"""

from __future__ import annotations

import logging

import httpx
import trafilatura

log = logging.getLogger("ainews.content")

_USER_AGENT = (
    "Mozilla/5.0 (compatible; ainews-bot/0.1; +https://github.com/ilariamartelli1/AINews) "
    "python-httpx"
)


def fetch_page(url: str, timeout: float = 25.0) -> str | None:
    """Fetch ``url`` and return extracted main-article text, or None on failure."""
    if not url:
        return None
    try:
        resp = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*"},
        )
        resp.raise_for_status()
    except Exception as exc:
        log.info("content fetch failed for %s: %s", url, exc)
        return None

    try:
        extracted = trafilatura.extract(
            resp.text,
            url=url,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
    except Exception as exc:
        log.info("content extraction failed for %s: %s", url, exc)
        return None

    if not extracted:
        return None
    return extracted.strip()
