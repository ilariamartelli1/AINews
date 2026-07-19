"""Comparative context — find related prior items via TF-IDF cosine similarity.

Given a candidate item and the pool of prior items from the archive, rank priors
by cosine similarity over TF-IDF vectors of their title+summary text and return
the top-K above a threshold. These become the article's "vs previous
tools/models" comparison links.

Pure-Python (no numpy/sklearn) to stay zero-cost and dependency-light. If TF-IDF
proves too coarse after release, this module is the single place to swap in
embeddings — the interface (candidate + priors -> ranked RelatedItem list) stays
the same.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .summarize.base import RelatedItem

_TOKEN = re.compile(r"[a-z0-9]+")

# Common words that carry no topical signal — dropped before vectorizing.
_STOP = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "being", "it", "its", "this", "that",
    "these", "those", "as", "at", "by", "from", "into", "than", "then", "so", "such",
    "will", "can", "has", "have", "had", "not", "no", "you", "your", "we", "our",
    "they", "their", "new", "now", "how", "what", "why", "who", "which", "more",
    "about", "up", "out", "over", "also", "his", "her",
}


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


@dataclass
class _Doc:
    id: int | None
    title: str
    url: str
    summary: str
    tf: Counter


def _doc_text(item: dict) -> str:
    return f"{item.get('title', '')} {item.get('summary', '')}"


def find_related(
    candidate: dict,
    priors: list[dict],
    top_k: int = 3,
    min_similarity: float = 0.08,
) -> list[RelatedItem]:
    """Rank ``priors`` by TF-IDF cosine similarity to ``candidate``.

    ``candidate`` and each prior are dicts with at least ``title``/``summary``
    (priors also carry ``id``/``url``). Returns up to ``top_k`` RelatedItems with
    similarity >= ``min_similarity``, most similar first.
    """
    if not priors:
        return []

    cand_doc = _Doc(None, candidate.get("title", ""), candidate.get("url", ""),
                    candidate.get("summary", ""), Counter(_tokenize(_doc_text(candidate))))
    prior_docs = [
        _Doc(p.get("id"), p.get("title", ""), p.get("url", ""), p.get("summary", ""),
             Counter(_tokenize(_doc_text(p))))
        for p in priors
    ]
    prior_docs = [d for d in prior_docs if d.tf]
    if not cand_doc.tf or not prior_docs:
        return []

    # IDF computed over the full corpus (candidate + priors).
    corpus = [cand_doc] + prior_docs
    n_docs = len(corpus)
    df: Counter = Counter()
    for d in corpus:
        df.update(d.tf.keys())
    idf = {term: math.log((n_docs + 1) / (freq + 1)) + 1.0 for term, freq in df.items()}

    def vec(d: _Doc) -> dict[str, float]:
        return {term: count * idf[term] for term, count in d.tf.items()}

    def cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        common = set(a) & set(b)
        dot = sum(a[t] * b[t] for t in common)
        if dot == 0.0:
            return 0.0
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0

    cand_vec = vec(cand_doc)
    scored: list[tuple[float, _Doc]] = []
    for d in prior_docs:
        sim = cosine(cand_vec, vec(d))
        if sim >= min_similarity:
            scored.append((sim, d))

    scored.sort(key=lambda t: -t[0])
    return [
        RelatedItem(title=d.title, url=d.url, similarity=round(sim, 4),
                    summary=d.summary, related_id=d.id)
        for sim, d in scored[:top_k]
    ]
