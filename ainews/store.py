"""SQLite data store for raw items + metadata.

This is the durable archive the PRD calls for: every candidate item ever seen is
persisted here with its provenance, fingerprints, and filtering verdict, so that
(a) deduplication works across days and (b) later stages (summarization,
publication) and the website archive can read from a single source of truth.

The store is intentionally thin — plain SQL, no ORM — to keep it zero-cost,
git-friendly (a single .db file), and easy to inspect.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Iterator

from .models import RawItem

if TYPE_CHECKING:
    from .article import Article


SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id         TEXT NOT NULL,
    url               TEXT NOT NULL,
    normalized_url    TEXT NOT NULL,
    url_fingerprint   TEXT NOT NULL UNIQUE,
    title_fingerprint TEXT NOT NULL,
    title             TEXT NOT NULL,
    summary           TEXT NOT NULL DEFAULT '',
    author            TEXT NOT NULL DEFAULT '',
    published_at      TEXT,
    fetched_at        TEXT NOT NULL,
    first_seen_at     TEXT NOT NULL,
    relevance_score   REAL NOT NULL DEFAULT 0,
    relevance_reasons TEXT NOT NULL DEFAULT '[]',
    status            TEXT NOT NULL DEFAULT 'new',
    metadata          TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_items_title_fp   ON items(title_fingerprint);
CREATE INDEX IF NOT EXISTS idx_items_status     ON items(status);
CREATE INDEX IF NOT EXISTS idx_items_source     ON items(source_id);
CREATE INDEX IF NOT EXISTS idx_items_published  ON items(published_at);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    stats        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS articles (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id           INTEGER NOT NULL UNIQUE REFERENCES items(id),
    title             TEXT NOT NULL,
    what_changed      TEXT NOT NULL DEFAULT '',
    why_it_matters    TEXT NOT NULL DEFAULT '',
    comparison        TEXT NOT NULL DEFAULT '',
    body              TEXT NOT NULL DEFAULT '',
    scope_tags        TEXT NOT NULL DEFAULT '[]',
    engine            TEXT NOT NULL DEFAULT '',
    model             TEXT NOT NULL DEFAULT '',
    quality_status    TEXT NOT NULL DEFAULT 'pending',
    quality_issues    TEXT NOT NULL DEFAULT '[]',
    published         INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_articles_item    ON articles(item_id);
CREATE INDEX IF NOT EXISTS idx_articles_quality ON articles(quality_status);
CREATE INDEX IF NOT EXISTS idx_articles_pub     ON articles(published);

CREATE TABLE IF NOT EXISTS article_sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    url         TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    source_id   TEXT NOT NULL DEFAULT '',
    is_primary  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_article_sources_article ON article_sources(article_id);

CREATE TABLE IF NOT EXISTS article_comparisons (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id       INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    related_item_id  INTEGER REFERENCES items(id),
    related_title    TEXT NOT NULL DEFAULT '',
    related_url      TEXT NOT NULL DEFAULT '',
    similarity       REAL NOT NULL DEFAULT 0,
    note             TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_article_comparisons_article ON article_comparisons(article_id);
"""

# Columns added to `items` after Sprint 1 — applied idempotently at open.
_ITEM_MIGRATIONS = [
    ("content", "TEXT NOT NULL DEFAULT ''"),
    ("content_fetched_at", "TEXT"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    """Thin wrapper over a SQLite connection holding the item archive."""

    def __init__(self, path: str | Path = "data/ainews.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self._migrate_items()
        self.conn.commit()

    def _migrate_items(self) -> None:
        """Add post-Sprint-1 columns to `items` if an older DB is missing them."""
        existing = {r[1] for r in self.conn.execute("PRAGMA table_info(items)")}
        for name, decl in _ITEM_MIGRATIONS:
            if name not in existing:
                self.conn.execute(f"ALTER TABLE items ADD COLUMN {name} {decl}")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Cursor]:
        cur = self.conn.cursor()
        try:
            yield cur
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cur.close()

    # --- Dedup lookups ----------------------------------------------------
    def seen_url_fingerprints(self, fingerprints: Iterable[str]) -> set[str]:
        fps = list({f for f in fingerprints if f})
        if not fps:
            return set()
        found: set[str] = set()
        # Chunk to stay under SQLite's variable limit.
        for i in range(0, len(fps), 500):
            chunk = fps[i:i + 500]
            q = f"SELECT url_fingerprint FROM items WHERE url_fingerprint IN ({','.join('?' * len(chunk))})"
            found.update(r[0] for r in self.conn.execute(q, chunk))
        return found

    def seen_title_fingerprints(self, fingerprints: Iterable[str]) -> set[str]:
        fps = list({f for f in fingerprints if f})
        if not fps:
            return set()
        found: set[str] = set()
        for i in range(0, len(fps), 500):
            chunk = fps[i:i + 500]
            q = f"SELECT title_fingerprint FROM items WHERE title_fingerprint IN ({','.join('?' * len(chunk))})"
            found.update(r[0] for r in self.conn.execute(q, chunk))
        return found

    def has_url(self, url_fingerprint: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM items WHERE url_fingerprint = ? LIMIT 1", (url_fingerprint,)
        ).fetchone()
        return row is not None

    # --- Writes -----------------------------------------------------------
    def insert_item(self, item: RawItem) -> bool:
        """Insert one item. Returns True if inserted, False if it already
        existed (same url_fingerprint). Never raises on duplicate."""
        with self._tx() as cur:
            cur.execute(
                """
                INSERT OR IGNORE INTO items (
                    source_id, url, normalized_url, url_fingerprint, title_fingerprint,
                    title, summary, author, published_at, fetched_at, first_seen_at,
                    relevance_score, relevance_reasons, status, metadata
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    item.source_id, item.url, item.normalized_url,
                    item.url_fingerprint, item.title_fingerprint,
                    item.title, item.summary, item.author, item.published_at,
                    item.fetched_at, _now(),
                    item.relevance_score, json.dumps(item.relevance_reasons),
                    item.status, json.dumps(item.metadata),
                ),
            )
            return cur.rowcount > 0

    def insert_items(self, items: Iterable[RawItem]) -> int:
        """Bulk insert; returns count of newly inserted rows."""
        inserted = 0
        for item in items:
            if self.insert_item(item):
                inserted += 1
        return inserted

    # --- Run bookkeeping --------------------------------------------------
    def start_run(self) -> int:
        with self._tx() as cur:
            cur.execute("INSERT INTO runs (started_at) VALUES (?)", (_now(),))
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, stats: dict[str, Any]) -> None:
        with self._tx() as cur:
            cur.execute(
                "UPDATE runs SET finished_at = ?, stats = ? WHERE id = ?",
                (_now(), json.dumps(stats), run_id),
            )

    # --- Reads (for later stages / inspection) ----------------------------
    def count(self, status: str | None = None) -> int:
        if status is None:
            row = self.conn.execute("SELECT COUNT(*) FROM items").fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM items WHERE status = ?", (status,)
            ).fetchone()
        return int(row[0])

    def recent(self, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if status is None:
            rows = self.conn.execute(
                "SELECT * FROM items ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM items WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        for k in ("relevance_reasons", "metadata", "scope_tags", "quality_issues"):
            if isinstance(d.get(k), str):
                try:
                    d[k] = json.loads(d[k])
                except json.JSONDecodeError:
                    pass
        return d

    # --- Article-generation support (Sprint 2) ---------------------------
    def set_item_content(self, url_fingerprint: str, content: str) -> None:
        """Cache scraped full-page text on the item so it's fetched once."""
        with self._tx() as cur:
            cur.execute(
                "UPDATE items SET content = ?, content_fetched_at = ? WHERE url_fingerprint = ?",
                (content, _now(), url_fingerprint),
            )

    def relevant_without_article(self, limit: int = 20) -> list[dict[str, Any]]:
        """Relevant items that don't yet have a generated article, newest first.

        Orders by published_at when available, else insertion order."""
        rows = self.conn.execute(
            """
            SELECT i.* FROM items i
            LEFT JOIN articles a ON a.item_id = i.id
            WHERE i.status = 'relevant' AND a.id IS NULL
            ORDER BY COALESCE(i.published_at, i.first_seen_at) DESC, i.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def prior_items_for_compare(self, exclude_item_id: int) -> list[dict[str, Any]]:
        """Candidate prior items for the comparison module: relevant items
        (article-backed preferred) excluding the candidate itself."""
        rows = self.conn.execute(
            """
            SELECT i.id, i.url, i.title, i.summary, i.published_at,
                   CASE WHEN a.id IS NULL THEN 0 ELSE 1 END AS has_article
            FROM items i
            LEFT JOIN articles a ON a.item_id = i.id
            WHERE i.status = 'relevant' AND i.id != ?
            """,
            (exclude_item_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def article_exists_for_item(self, item_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM articles WHERE item_id = ? LIMIT 1", (item_id,)
        ).fetchone()
        return row is not None

    def insert_article(self, article: "Article") -> int:
        """Persist an article plus its sources and comparison links atomically.

        Returns the new article id. Raises on a duplicate item_id (one article
        per item)."""
        with self._tx() as cur:
            cur.execute(
                """
                INSERT INTO articles (
                    item_id, title, what_changed, why_it_matters, comparison, body,
                    scope_tags, engine, model, quality_status, quality_issues,
                    published, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    article.item_id, article.title, article.what_changed,
                    article.why_it_matters, article.comparison, article.body,
                    json.dumps(article.scope_tags), article.engine, article.model,
                    article.quality_status, json.dumps(article.quality_issues),
                    int(article.published), article.created_at,
                ),
            )
            article_id = int(cur.lastrowid)
            for s in article.sources:
                cur.execute(
                    "INSERT INTO article_sources (article_id, url, title, source_id, is_primary) "
                    "VALUES (?,?,?,?,?)",
                    (article_id, s.url, s.title, s.source_id, int(s.is_primary)),
                )
            for c in article.comparisons:
                cur.execute(
                    "INSERT INTO article_comparisons "
                    "(article_id, related_item_id, related_title, related_url, similarity, note) "
                    "VALUES (?,?,?,?,?,?)",
                    (article_id, c.related_item_id, c.related_title, c.related_url,
                     c.similarity, c.note),
                )
            return article_id

    def count_articles(self, quality_status: str | None = None) -> int:
        if quality_status is None:
            row = self.conn.execute("SELECT COUNT(*) FROM articles").fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM articles WHERE quality_status = ?", (quality_status,)
            ).fetchone()
        return int(row[0])

    def recent_articles(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM articles ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_article(self, article_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
        if row is None:
            return None
        art = self._row_to_dict(row)
        art["sources"] = [dict(r) for r in self.conn.execute(
            "SELECT url, title, source_id, is_primary FROM article_sources WHERE article_id = ?",
            (article_id,))]
        art["comparisons"] = [dict(r) for r in self.conn.execute(
            "SELECT related_item_id, related_title, related_url, similarity, note "
            "FROM article_comparisons WHERE article_id = ?", (article_id,))]
        return art
