# AINews - automated AI news blog

Fully automated pipeline that discovers, filters, deduplicates, and archives
highly-specific AI news (new models, tools, frameworks, paradigms). See
[ai-news-blog-prd.md](ai-news-blog-prd.md) for the product spec.

**Sprint 1 (this code): Discovery & Scope.** Later sprints add summarization,
comparative context, publication, and the blog website.

## What it does (Sprint 1)

```
fetch (pluggable sources) → dedupe (within-batch + cross-run) → relevance/novelty filter → persist (SQLite archive)
```

- **Editorial scope** ([config/scope.yaml](config/scope.yaml)) — the single knob
  defining what the blog covers: topics, keywords, novelty signals, exclusions,
  and scoring weights. Retarget the whole product to a new niche by editing this
  file alone.
- **Pluggable sources** ([config/sources.yaml](config/sources.yaml)) — daily
  discovery from RSS feeds today; add API/scraper source types by registering a
  new plugin (see below).
- **Relevance & novelty filter** — zero-cost, rule-based scoring that favors
  concrete announcements over generic commentary. Recall-favoring first pass; a
  later LLM pass will tighten precision.
- **Deduplication** — URL- and title-fingerprint dedup, both within a batch and
  across all previous runs, so the same development is never processed twice.
- **Archive** — every candidate item + metadata + verdict persisted to a single
  SQLite file ([data/ainews.db](data/)) for later stages and historical lookup.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Usage

```bash
ainews run              # one discovery pass (the daily job)
ainews stats            # archive counts by status
ainews list relevant    # show recent relevant candidates
ainews list irrelevant -n 10
ainews -v run           # verbose logging
```

Config/DB paths are overridable: `--scope`, `--sources`, `--db`.

Runs are **idempotent**: a second run over unchanged feeds inserts nothing
(everything deduped), so it is safe to schedule daily (cron / GitHub Actions —
wired up in a later sprint) at zero cost.

## Retargeting the scope

Edit [config/scope.yaml](config/scope.yaml) — e.g. to focus on AI image
generation, swap `strong_keywords`/`topics` for diffusion/image terms and tune
`scoring.min_score`. No code changes required.

## Adding a new source type

```python
# ainews/sources/myapi.py
from ..models import RawItem
from .base import Source, register

@register("myapi")
class MyApiSource(Source):
    def fetch(self) -> list[RawItem]:
        ...  # return list[RawItem]; skip bad entries, don't crash the run
```

Import it in [ainews/sources/__init__.py](ainews/sources/__init__.py), then add
an entry with `type: myapi` to `config/sources.yaml`.

## Architecture

| Module | Responsibility |
|---|---|
| [ainews/config.py](ainews/config.py) | scope + source config models (YAML) |
| [ainews/models.py](ainews/models.py) | `RawItem`, URL/title normalization, fingerprints |
| [ainews/sources/](ainews/sources/) | pluggable source interface + registry + RSS plugin |
| [ainews/relevance.py](ainews/relevance.py) | rule-based relevance/novelty scoring |
| [ainews/dedup.py](ainews/dedup.py) | within-batch + cross-run deduplication |
| [ainews/store.py](ainews/store.py) | SQLite archive |
| [ainews/pipeline.py](ainews/pipeline.py) | orchestrator |
| [ainews/cli.py](ainews/cli.py) | `ainews` CLI |

## Tests

```bash
.venv/bin/pytest -q
```
