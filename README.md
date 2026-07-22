# AINews - automated AI news blog

Fully automated pipeline that discovers, filters, deduplicates, and archives
highly-specific AI news (new models, tools, frameworks, paradigms). See
[ai-news-blog-prd.md](ai-news-blog-prd.md) for the product spec.

**Sprint 1: Discovery & Scope.** **Sprint 2: Article Generation & Context.**
**Sprint 3: Website & Archive.** **Sprint 4: Automation & Ops.** — the product is
complete: a scheduled cloud job runs the whole pipeline daily and publishes.

## What it does

**Sprint 1 — discovery:**
```
fetch (pluggable sources) → dedupe (within-batch + cross-run) → relevance/novelty filter → persist (SQLite archive)
```

**Sprint 2 — article generation:**
```
select relevant item → fetch full page (cache) → find related priors (TF-IDF) → summarize (Claude, extractive fallback) → quality-check → persist article + sources + comparison links
```

**Sprint 3 — website:**
```
published articles (quality=pass) → static site: post list + single posts + searchable archive + RSS/JSON feeds
```

**Sprint 4 — daily automation (one command, run in the cloud):**
```
ainews daily = discover → filter → dedupe → summarize → compare → publish → health verdict
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
- **Static website** ([ainews/site/](ainews/site/)) — renders the archive into a
  blog-first static site: post list, single-post pages (with sources and
  comparison links shown for transparency), a client-side **searchable archive**
  (filter by date / source / tag + full-text), and **RSS + JSON feeds**. Only
  quality-`pass` articles are published. Host-agnostic output — open locally or
  deploy to any static host.
- **Daily automation** ([ainews/daily.py](ainews/daily.py) + [.github/workflows/daily.yml](.github/workflows/daily.yml))
  — `ainews daily` runs the whole pipeline end-to-end and writes a health verdict.
  A GitHub Actions cron runs it in the cloud (your PC stays off), commits the
  archive DB back for persistence, deploys the site to Cloudflare Pages, and
  **alerts** on failures / empty-news days.
- **Monitoring** ([ainews/monitor.py](ainews/monitor.py)) — evaluates each run as
  `ok` / `empty_news` / `failure`. Failures fail the CI job (native email) and,
  with empty-news days, open/append a GitHub Issue labelled `ainews-alert`.

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
ainews build            # render the static website into ./site
ainews build --base-url https://ai.example.com   # absolute feed URLs
ainews daily            # full pipeline: discover→filter→dedupe→summarize→compare→publish
ainews daily --generate-limit 50 --base-url https://ai.example.com
ainews -v run           # verbose logging
```

`ainews daily` writes a health verdict + full report to `data/last_run.json` and
exits non-zero only on failure (empty-news days pass unless `--fail-on-empty`).

After `build`, open `site/index.html` in a browser. The site is plain static
files (HTML/CSS/JS + `feed.xml` / `feed.json` / `search.json`).

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

This single YAML file **is** the admin/config surface — there is no separate
admin app to secure. Edit it locally, or via GitHub's web editor from any
browser; the daily automation (a later sprint) rebuilds the site on change.

## Hosting (private, zero-cost)

The build output is static, so it can be hosted free. To keep it **private (only
you) and always-on without your PC running**:

- **Cloudflare Pages + Cloudflare Access** (recommended) — free static hosting +
  free access control that gates the site behind your Google/email login.
  Point Pages at the built `site/` directory (or the Actions artifact).
- **GitHub Pages** — free and always-on, but **public** on free plans.
- **Local** — just open `site/index.html`; private but only while your PC is on.

The build itself is host-agnostic; pass `--base-url https://<your-domain>` so the
RSS/JSON feed links are absolute.

## Daily automation setup (GitHub Actions)

[.github/workflows/daily.yml](.github/workflows/daily.yml) runs `ainews daily` on a
cron (07:00 UTC), commits `data/ainews.db` back (so dedup + archive persist across
runs), deploys `site/` to Cloudflare Pages, and opens a GitHub Issue on
failure / empty-news days. To enable it, set in the repo:

**Secrets** (Settings → Secrets and variables → Actions → Secrets):
- `ANTHROPIC_API_KEY` — for the LLM summarizer (omit if using `type: extractive`).
- `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` — for the Cloudflare Pages deploy.

**Variables** (same page → Variables):
- `SITE_BASE_URL` — e.g. `https://ainews.pages.dev` (absolute feed links).
- `CLOUDFLARE_PROJECT` — Pages project name (default `ainews`).
- `GENERATE_LIMIT` — max articles/day (default `50`; caps daily LLM cost).

One-time Cloudflare setup: create a Pages project, generate an API token with the
Pages:Edit permission, and (for private access) enable **Cloudflare Access** on the
project restricted to your login. The archive DB is committed by the workflow —
the first run seeds it; subsequent runs append. Cost stays near-zero: Actions cron
+ Cloudflare Pages are free; the only spend is the Haiku summarizer (~cents/day).

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
| [ainews/site/](ainews/site/) | static site generator (builder, templates, CSS/JS) |
| [ainews/daily.py](ainews/daily.py) | full daily pipeline orchestrator + status file |
| [ainews/monitor.py](ainews/monitor.py) | health evaluation + alert formatting |
| [.github/workflows/daily.yml](.github/workflows/daily.yml) | scheduled cloud run: cron → pipeline → commit DB → deploy → alert |
| [ainews/cli.py](ainews/cli.py) | `ainews` CLI |

## Tests

```bash
.venv/bin/pytest -q
```
