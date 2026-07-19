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
from typing import Any, Iterable, Iterator

from .models import RawItem


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
"""


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
        self.conn.commit()

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
        for k in ("relevance_reasons", "metadata"):
            if isinstance(d.get(k), str):
                try:
                    d[k] = json.loads(d[k])
                except json.JSONDecodeError:
                    pass
        return d
