# AINews - automated AI news blog

Fully automated pipeline that discovers, filters, deduplicates, and archives
highly-specific AI news (new models, tools, frameworks, paradigms). See
[ai-news-blog-prd.md](ai-news-blog-prd.md) for the product spec.

**Sprint 1: Discovery & Scope.** **Sprint 2: Article Generation & Context.**
Later sprints add publication and the blog website.

## What it does

**Sprint 1 — discovery:**
```
fetch (pluggable sources) → dedupe (within-batch + cross-run) → relevance/novelty filter → persist (SQLite archive)
```

**Sprint 2 — article generation:**
```
select relevant item → fetch full page (cache) → find related priors (TF-IDF) → summarize (Claude, extractive fallback) → quality-check → persist article + sources + comparison links
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
- **Article generation** ([config/summarizer.yaml](config/summarizer.yaml)) — turns
  a selected item into a short structured post (*what changed / why it matters /
  how it compares*). Pluggable summarizer: **extractive** (zero-cost, offline) or
  **llm** (Claude via the Anthropic API). Swap by config, no pipeline rewrite.
- **Comparative context** — TF-IDF cosine over the archive finds related prior
  items; the post frames the new item against them and stores the links.
- **Full-page input** — scrapes the source article (trafilatura) for a richer
  summary than the feed blurb; extracted text is cached on the item.
- **Quality checks** — length, missing sources, empty/placeholder/refusal text,
  and comparison presence are checked before an article is marked publishable.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Usage

```bash
ainews run              # one discovery pass (the daily job)
ainews generate         # write articles for relevant, unwritten items
ainews generate -n 5    # cap how many to write this run
ainews stats            # archive + article counts by status
ainews list relevant    # show recent relevant candidates
ainews articles         # show recent generated articles + comparison links
ainews -v run           # verbose logging
```

Config/DB paths are overridable: `--scope`, `--sources`, `--summarizer`, `--db`.

### LLM (Claude) summarizer

`config/summarizer.yaml` defaults to `type: llm` (model `claude-opus-4-8`). The
Anthropic client reads the key from the environment:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # or an `ant auth login` profile
ainews generate -n 5
```

Any per-item LLM failure (bad key, rate limit) falls back to the zero-cost
**extractive** engine, so a run never blocks. For fully offline / zero-cost
generation, set `type: extractive` in `config/summarizer.yaml`. For lower LLM cost
at volume, set `model: claude-haiku-4-5` or `claude-sonnet-5`.

> **Cost note:** the LLM path is the one paid component and runs against the PRD's
> zero-cost goal — it's opt-in via config. The extractive engine keeps the whole
> pipeline zero-cost.

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
| [ainews/store.py](ainews/store.py) | SQLite archive (items + articles + sources + comparisons) |
| [ainews/pipeline.py](ainews/pipeline.py) | discovery orchestrator |
| [ainews/article.py](ainews/article.py) | article schema (`ArticleDraft`, `Article`, sources, comparison links) |
| [ainews/content.py](ainews/content.py) | full-page fetch + extraction (trafilatura) |
| [ainews/summarize/](ainews/summarize/) | pluggable summarizer interface + extractive + Claude engines |
| [ainews/compare.py](ainews/compare.py) | TF-IDF cosine comparative context |
| [ainews/quality.py](ainews/quality.py) | pre-publication quality checks |
| [ainews/generate.py](ainews/generate.py) | article-generation orchestrator |
| [ainews/cli.py](ainews/cli.py) | `ainews` CLI |

## Tests

```bash
.venv/bin/pytest -q
```
