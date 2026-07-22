import json

from ainews.config import SourceConfig, SummarizerConfig
from ainews.daily import run_daily, write_status
from ainews import monitor
from ainews.models import RawItem
from ainews.sources.base import register, Source
from ainews.store import Store


@register("fake-daily")
class _FakeSource(Source):
    def fetch(self):
        return [RawItem(source_id=self.id, url=s["url"], title=s["title"],
                        summary=s.get("summary", ""), metadata={"source_weight": self.weight})
                for s in self.options.get("items", [])]


@register("boom-daily")
class _BoomSource(Source):
    def fetch(self):
        raise RuntimeError("feed down")


def _sconfig():
    return SummarizerConfig(type="extractive", fetch_full_page=False, min_words=10, max_words=400)


def _src(id, items, weight=2.0):
    return SourceConfig(id=id, type="fake-daily", weight=weight, options={"items": items})


def test_daily_ok_end_to_end(tmp_path, scope):
    sources = [_src("s", [{
        "url": "https://a.com/1",
        "title": "Acme launches a new open-source large language model API",
        "summary": "Acme launched an open-source large language model with a Python SDK "
                   "and a large context window for developers building agents.",
    }])]
    with Store(tmp_path / "t.db") as store:
        report = run_daily(scope, sources, _sconfig(), store, tmp_path / "site",
                           base_url="https://ex.com", now="2026-07-22T07:00:00+00:00")

    assert report.ok
    assert report.discovery["relevant"] >= 1
    assert report.generation["generated"] >= 1
    assert report.site["posts"] >= 1
    assert (tmp_path / "site" / "index.html").exists()

    health = monitor.evaluate(report)
    assert health.status == monitor.OK
    assert not health.needs_alert


def test_daily_empty_news(tmp_path, scope):
    # Only generic commentary → nothing relevant, nothing generated.
    sources = [_src("s", [{
        "url": "https://a.com/2",
        "title": "Opinion: the top 10 AI podcast episodes",
        "summary": "a podcast opinion piece",
    }], weight=0.0)]
    with Store(tmp_path / "t.db") as store:
        report = run_daily(scope, sources, _sconfig(), store, tmp_path / "site")

    assert report.ok
    health = monitor.evaluate(report)
    assert health.status == monitor.EMPTY
    assert health.needs_alert


def test_daily_all_sources_failed_is_failure(tmp_path, scope):
    sources = [SourceConfig(id="broken", type="boom-daily")]
    with Store(tmp_path / "t.db") as store:
        report = run_daily(scope, sources, _sconfig(), store, tmp_path / "site")

    # Pipeline itself doesn't raise (per-source errors isolated), but health
    # flags all-sources-failed as a failure.
    health = monitor.evaluate(report)
    assert health.status == monitor.FAILURE
    assert health.is_failure


def test_write_status_file(tmp_path, scope):
    sources = [_src("s", [{
        "url": "https://a.com/1",
        "title": "New framework releases with an SDK",
        "summary": "a large language model framework with a Python SDK",
    }])]
    with Store(tmp_path / "t.db") as store:
        report = run_daily(scope, sources, _sconfig(), store, tmp_path / "site")
    health = monitor.evaluate(report)
    status_path = tmp_path / "last_run.json"
    write_status(report, health, status_path)

    payload = json.loads(status_path.read_text())
    assert payload["health"]["status"] in (monitor.OK, monitor.EMPTY, monitor.FAILURE)
    assert "report" in payload
    assert "discovery" in payload["report"]


def test_alert_formatting():
    h = monitor.Health(monitor.FAILURE, "pipeline failed: boom",
                       {"error": "RuntimeError: boom", "discovery": {}, "generation": {}})
    title, body = monitor.format_alert(h, repo_run_url="https://gh/run/1")
    assert "failure" in title.lower()
    assert "boom" in body
    assert "https://gh/run/1" in body
