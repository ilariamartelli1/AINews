"""Deduplication.

Two layers, both keyed on the fingerprints defined on :class:`RawItem`:

1. **Within-batch** — the same story often appears in several feeds on the same
   day (identical URL, or same headline under different URLs). Collapse those to
   one, preferring the higher-trust source.

2. **Cross-run** — an item (or the same event under a new URL) may have been seen
   on a previous day. Check the store's persisted fingerprints and drop repeats.

This gives the PRD guarantee that a single underlying development is never
processed — and therefore never published — twice.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import RawItem
from .store import Store


@dataclass
class DedupResult:
    unique: list[RawItem]        # items to keep (not seen before, deduped within batch)
    duplicates: list[RawItem]    # items dropped as repeats (status set to "duplicate")


def _source_weight(item: RawItem) -> float:
    return float(item.metadata.get("source_weight", 0.0))


def dedupe_within_batch(items: list[RawItem]) -> tuple[list[RawItem], list[RawItem]]:
    """Collapse duplicates inside a single fetch batch.

    An item is a duplicate of an already-kept one if it shares a URL fingerprint
    or a (non-empty) title fingerprint. On collision the higher source-weight
    item wins; ties keep the first seen.
    """
    kept: list[RawItem] = []
    seen_url: dict[str, int] = {}    # url_fp   -> index in kept
    seen_title: dict[str, int] = {}  # title_fp -> index in kept
    duplicates: list[RawItem] = []

    for item in items:
        ufp = item.url_fingerprint
        tfp = item.title_fingerprint if item.normalized_title else None

        clash_idx = seen_url.get(ufp)
        if clash_idx is None and tfp is not None:
            clash_idx = seen_title.get(tfp)

        if clash_idx is None:
            idx = len(kept)
            kept.append(item)
            seen_url[ufp] = idx
            if tfp is not None:
                seen_title[tfp] = idx
            continue

        # Collision — keep whichever has the higher source weight.
        incumbent = kept[clash_idx]
        if _source_weight(item) > _source_weight(incumbent):
            incumbent.status = "duplicate"
            duplicates.append(incumbent)
            kept[clash_idx] = item
            seen_url[item.url_fingerprint] = clash_idx
            if item.normalized_title:
                seen_title[item.title_fingerprint] = clash_idx
        else:
            item.status = "duplicate"
            duplicates.append(item)

    return kept, duplicates


def dedupe(items: list[RawItem], store: Store) -> DedupResult:
    """Full dedup: within-batch, then against the persisted archive."""
    batch_unique, batch_dupes = dedupe_within_batch(items)

    # Cross-run: query the store once for all fingerprints in the batch.
    seen_urls = store.seen_url_fingerprints(i.url_fingerprint for i in batch_unique)
    seen_titles = store.seen_title_fingerprints(
        i.title_fingerprint for i in batch_unique if i.normalized_title
    )

    unique: list[RawItem] = []
    duplicates: list[RawItem] = list(batch_dupes)
    for item in batch_unique:
        is_dup = item.url_fingerprint in seen_urls or (
            item.normalized_title and item.title_fingerprint in seen_titles
        )
        if is_dup:
            item.status = "duplicate"
            duplicates.append(item)
        else:
            unique.append(item)

    return DedupResult(unique=unique, duplicates=duplicates)
