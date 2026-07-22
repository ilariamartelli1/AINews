"""Command-line entry point.

    ainews run            # fetch -> dedupe -> filter -> persist (the daily job)
    ainews stats          # archive counts by status
    ainews list [status]  # show recent items (optionally by status)

Runs zero-cost and unattended; intended to be driven by a daily scheduler
(cron / GitHub Actions) in a later sprint.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import ScopeConfig, SummarizerConfig, load_sources
from .daily import run_daily, write_status, DEFAULT_STATUS_FILE
from .generate import generate as run_generate
from . import monitor
from .pipeline import run as run_pipeline
from .site import build_site
from .store import Store

DEFAULT_SCOPE = "config/scope.yaml"
DEFAULT_SOURCES = "config/sources.yaml"
DEFAULT_SUMMARIZER = "config/summarizer.yaml"
DEFAULT_DB = "data/ainews.db"
DEFAULT_SITE_OUT = "site"


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--scope", default=DEFAULT_SCOPE, help="path to scope.yaml")
    p.add_argument("--sources", default=DEFAULT_SOURCES, help="path to sources.yaml")
    p.add_argument("--db", default=DEFAULT_DB, help="path to SQLite archive")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ainews", description="AI news discovery pipeline")
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose logging")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="run one discovery pass")
    _add_common(p_run)

    p_stats = sub.add_parser("stats", help="show archive stats")
    _add_common(p_stats)

    p_list = sub.add_parser("list", help="list recent items")
    p_list.add_argument("status", nargs="?", default=None,
                        help="filter: new|relevant|irrelevant|duplicate")
    p_list.add_argument("-n", "--limit", type=int, default=20)
    _add_common(p_list)

    p_gen = sub.add_parser("generate", help="generate articles for relevant items")
    p_gen.add_argument("-n", "--limit", type=int, default=20,
                       help="max items to write articles for")
    p_gen.add_argument("--summarizer", default=DEFAULT_SUMMARIZER,
                       help="path to summarizer.yaml")
    _add_common(p_gen)

    p_arts = sub.add_parser("articles", help="list recent generated articles")
    p_arts.add_argument("-n", "--limit", type=int, default=20)
    _add_common(p_arts)

    p_build = sub.add_parser("build", help="build the static website from published articles")
    p_build.add_argument("--out", default=DEFAULT_SITE_OUT, help="output directory")
    p_build.add_argument("--base-url", default="",
                         help="absolute site URL (for feed links, e.g. https://ai.example.com)")
    _add_common(p_build)

    p_daily = sub.add_parser("daily", help="run the full daily pipeline (discover→publish)")
    p_daily.add_argument("--out", default=DEFAULT_SITE_OUT, help="site output directory")
    p_daily.add_argument("--base-url", default="", help="absolute site URL for feed links")
    p_daily.add_argument("--summarizer", default=DEFAULT_SUMMARIZER, help="path to summarizer.yaml")
    p_daily.add_argument("--generate-limit", type=int, default=50,
                        help="max articles to generate this run (caps daily LLM cost)")
    p_daily.add_argument("--status-file", default=DEFAULT_STATUS_FILE,
                        help="where to write the run health + report JSON")
    p_daily.add_argument("--fail-on-empty", action="store_true",
                        help="exit non-zero on an empty-news day (default: only on failure)")
    _add_common(p_daily)

    return parser


def cmd_run(args: argparse.Namespace) -> int:
    scope = ScopeConfig.load(args.scope)
    sources = load_sources(args.sources)
    print(f"scope: {scope.name}  ({len(sources)} sources configured)")
    with Store(args.db) as store:
        report = run_pipeline(scope, sources, store)
    print(json.dumps(report.as_dict(), indent=2))
    if report.source_errors:
        print(f"\n{len(report.source_errors)} source(s) errored (run continued).", file=sys.stderr)
    print(f"\nrelevant candidates this run: {report.relevant}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    with Store(args.db) as store:
        total = store.count()
        print(f"archive: {args.db}")
        print(f"total items: {total}")
        for status in ("relevant", "irrelevant", "duplicate", "new"):
            print(f"  {status:11s}: {store.count(status)}")
        print(f"articles: {store.count_articles()}")
        for status in ("pass", "flagged", "fail"):
            print(f"  {status:11s}: {store.count_articles(status)}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    with Store(args.db) as store:
        rows = store.recent(status=args.status, limit=args.limit)
    for r in rows:
        print(f"[{r['status']:10s}] {r['relevance_score']:>6.2f}  {r['title']}")
        print(f"             {r['source_id']}  {r['url']}")
    if not rows:
        print("(no items)")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    scope = ScopeConfig.load(args.scope)
    sconfig = SummarizerConfig.load(args.summarizer)
    print(f"scope: {scope.name}  summarizer: {sconfig.type}"
          + (f" ({sconfig.model})" if sconfig.type == "llm" else ""))
    with Store(args.db) as store:
        report = run_generate(scope, sconfig, store, limit=args.limit)
    print(json.dumps(report.as_dict(), indent=2))
    if report.errors:
        print(f"\n{len(report.errors)} item(s) errored (run continued).", file=sys.stderr)
    print(f"\narticles generated: {report.generated} "
          f"(pass={report.passed} flagged={report.flagged} fail={report.failed_quality})")
    return 0


def cmd_articles(args: argparse.Namespace) -> int:
    with Store(args.db) as store:
        rows = store.recent_articles(limit=args.limit)
        for r in rows:
            print(f"#{r['id']} [{r['quality_status']:8s}] {r['title']}")
            art = store.get_article(r["id"])
            for c in art.get("comparisons", []):
                print(f"      ↳ vs {c['related_title']}  (sim {c['similarity']})")
    if not rows:
        print("(no articles)")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    from pathlib import Path
    scope_path = args.scope if Path(args.scope).exists() else None
    stats = build_site(args.db, args.out, scope_path=scope_path, base_url=args.base_url)
    print(f"built site -> {args.out}/  "
          f"({stats['posts']} posts, {stats['sources']} sources, {stats['tags']} tags)")
    print(f"open {args.out}/index.html")
    return 0


def cmd_daily(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone
    scope = ScopeConfig.load(args.scope)
    sources = load_sources(args.sources)
    sconfig = SummarizerConfig.load(args.summarizer)
    now = datetime.now(timezone.utc).isoformat()
    print(f"scope: {scope.name}  summarizer: {sconfig.type}  "
          f"generate-limit: {args.generate_limit}")

    with Store(args.db) as store:
        report = run_daily(scope, sources, sconfig, store, args.out,
                           base_url=args.base_url, generate_limit=args.generate_limit,
                           now=now)

    health = monitor.evaluate(report)
    write_status(report, health, args.status_file)

    print(json.dumps(report.as_dict(), indent=2))
    print(f"\nhealth: {health.status} — {health.summary}")
    print(f"status written to {args.status_file}")

    if health.is_failure:
        return 1                                   # trigger CI failure alert
    if health.status == monitor.EMPTY and args.fail_on_empty:
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if not args.command:
        parser.print_help()
        return 1

    handlers = {
        "run": cmd_run, "stats": cmd_stats, "list": cmd_list,
        "generate": cmd_generate, "articles": cmd_articles, "build": cmd_build,
        "daily": cmd_daily,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
