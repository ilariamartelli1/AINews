"""Static site generator (Sprint 3).

Renders the SQLite archive into a blog-first static site: a post list, one page
per article (with its sources and comparison links), a client-side searchable
archive, and RSS + JSON feeds. Output is plain static files — open locally, or
deploy to any static host (Cloudflare Pages recommended; see README).
"""

from .build import SiteBuilder, build_site

__all__ = ["SiteBuilder", "build_site"]
