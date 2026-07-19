"""Static site builder.

Reads published articles from the store and writes a self-contained static site:

    index.html          blog-first list of recent posts
    posts/<id>.html     single article view (body + sources + comparisons)
    archive.html        searchable archive (client-side facets: date/source/tag)
    search.json         index consumed by archive.js
    feed.xml            RSS 2.0 feed
    feed.json           JSON Feed 1.1
    static/             CSS + archive JS (copied verbatim)

Host-agnostic: links between pages are relative so the site works opened from
disk or served from any static host. ``base_url`` is used only for the absolute
URLs required by the feeds.
"""

from __future__ import annotations

import html
import json
import re
import shutil
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import ScopeConfig
from ..store import Store

_TEMPLATES = Path(__file__).parent / "templates"
_STATIC = Path(__file__).parent / "static"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _paragraphs(text: str) -> list[dict[str, Any]]:
    """Split a text field into renderable blocks: paragraphs and bullet lists.

    Handles both the extractive engine's "- item" lists and the LLM engine's
    prose. Returns dicts the template renders as <p> or <ul>."""
    if not text:
        return []
    blocks: list[dict[str, Any]] = []
    bullets: list[str] = []

    def flush():
        if bullets:
            blocks.append({"type": "list", "items": bullets.copy()})
            bullets.clear()

    for line in text.splitlines():
        line = line.strip()
        if not line:
            flush()
            continue
        if line.startswith("- "):
            bullets.append(line[2:].strip())
        else:
            flush()
            blocks.append({"type": "para", "text": line})
    flush()
    return blocks


class SiteBuilder:
    def __init__(self, store: Store, scope: ScopeConfig | None = None,
                 base_url: str = "", site_title: str | None = None,
                 feed_limit: int = 50) -> None:
        self.store = store
        self.scope = scope
        self.base_url = base_url.rstrip("/")
        self.site_title = site_title or (scope.name if scope else "AI News")
        self.site_description = (scope.description.strip() if scope and scope.description
                                 else "Highly-filtered, practical AI news.")
        self.feed_limit = feed_limit
        self.env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.built_at = datetime.now(timezone.utc)

    # --- view model -------------------------------------------------------
    def _view(self, art: dict[str, Any]) -> dict[str, Any]:
        dt = _parse_dt(art.get("item_published_at")) or _parse_dt(art.get("created_at"))
        primary = next((s for s in art["sources"] if s.get("is_primary")),
                       art["sources"][0] if art["sources"] else {})
        return {
            "id": art["id"],
            "title": art["title"],
            "permalink": f"posts/{art['id']}.html",
            "date": dt,
            "date_display": dt.strftime("%b %d, %Y") if dt else "",
            "date_iso": dt.date().isoformat() if dt else "",
            "source": art.get("item_source_id", ""),
            "primary_url": primary.get("url", art.get("item_url", "")),
            "tags": art.get("scope_tags", []) or [],
            "what_changed": art["what_changed"],
            "why_it_matters": art["why_it_matters"],
            "what_changed_blocks": _paragraphs(art["what_changed"]),
            "why_blocks": _paragraphs(art["why_it_matters"]),
            "comparison_blocks": _paragraphs(art.get("comparison", "")),
            "sources": art["sources"],
            "comparisons": art["comparisons"],
            "engine": art.get("engine", ""),
        }

    # --- build ------------------------------------------------------------
    def build(self, out_dir: str | Path) -> dict[str, int]:
        out = Path(out_dir)
        (out / "posts").mkdir(parents=True, exist_ok=True)

        articles = self.store.published_articles()
        views = [self._view(a) for a in articles]

        ctx_base = {
            "site_title": self.site_title,
            "site_description": self.site_description,
            "built_at": self.built_at,
            "base_url": self.base_url,
        }

        # index
        (out / "index.html").write_text(
            self.env.get_template("index.html").render(
                posts=views, page="home", **ctx_base),
            encoding="utf-8")

        # single posts
        for v in views:
            (out / "posts" / f"{v['id']}.html").write_text(
                self.env.get_template("post.html").render(
                    post=v, page="post", rel="../", **ctx_base),
                encoding="utf-8")

        # archive + search index
        sources = sorted({v["source"] for v in views if v["source"]})
        tags = sorted({t for v in views for t in v["tags"]})
        (out / "archive.html").write_text(
            self.env.get_template("archive.html").render(
                posts=views, sources=sources, tags=tags, page="archive", **ctx_base),
            encoding="utf-8")
        (out / "search.json").write_text(
            json.dumps(self._search_index(views), ensure_ascii=False),
            encoding="utf-8")

        # feeds
        (out / "feed.xml").write_text(self._render_rss(views), encoding="utf-8")
        (out / "feed.json").write_text(self._render_json_feed(views), encoding="utf-8")

        # static assets
        shutil.copytree(_STATIC, out / "static", dirs_exist_ok=True)

        return {"posts": len(views), "sources": len(sources), "tags": len(tags)}

    def _search_index(self, views: list[dict]) -> list[dict]:
        return [{
            "id": v["id"],
            "title": v["title"],
            "url": v["permalink"],
            "date": v["date_iso"],
            "source": v["source"],
            "tags": v["tags"],
            "text": f"{v['title']} {v['what_changed']} {v['why_it_matters']}".lower(),
        } for v in views]

    # --- feeds ------------------------------------------------------------
    def _abs(self, rel: str) -> str:
        return f"{self.base_url}/{rel}" if self.base_url else rel

    def _render_rss(self, views: list[dict]) -> str:
        items = []
        for v in views[: self.feed_limit]:
            pub = format_datetime(v["date"]) if v["date"] else ""
            desc = html.escape(v["what_changed"])
            link = self._abs(v["permalink"])
            items.append(
                "<item>"
                f"<title>{html.escape(v['title'])}</title>"
                f"<link>{html.escape(link)}</link>"
                f"<guid isPermaLink=\"false\">ainews-{v['id']}</guid>"
                + (f"<pubDate>{pub}</pubDate>" if pub else "")
                + f"<description>{desc}</description>"
                + "".join(f"<category>{html.escape(t)}</category>" for t in v["tags"])
                + "</item>"
            )
        now = format_datetime(self.built_at)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0"><channel>'
            f"<title>{html.escape(self.site_title)}</title>"
            f"<link>{html.escape(self.base_url or 'index.html')}</link>"
            f"<description>{html.escape(self.site_description)}</description>"
            f"<lastBuildDate>{now}</lastBuildDate>"
            + "".join(items)
            + "</channel></rss>\n"
        )

    def _render_json_feed(self, views: list[dict]) -> str:
        feed = {
            "version": "https://jsonfeed.org/version/1.1",
            "title": self.site_title,
            "description": self.site_description,
            "home_page_url": self._abs("index.html"),
            "feed_url": self._abs("feed.json"),
            "items": [{
                "id": str(v["id"]),
                "url": self._abs(v["permalink"]),
                "title": v["title"],
                "content_text": f"{v['what_changed']}\n\n{v['why_it_matters']}".strip(),
                "date_published": v["date"].isoformat() if v["date"] else None,
                "tags": v["tags"],
            } for v in views[: self.feed_limit]],
        }
        return json.dumps(feed, ensure_ascii=False, indent=2)


def build_site(db_path: str | Path, out_dir: str | Path,
               scope_path: str | Path | None = None,
               base_url: str = "") -> dict[str, int]:
    scope = ScopeConfig.load(scope_path) if scope_path else None
    with Store(db_path) as store:
        return SiteBuilder(store, scope=scope, base_url=base_url).build(out_dir)
