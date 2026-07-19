from ainews.config import SourceConfig
from ainews.models import RawItem
from ainews.pipeline import run
from ainews.sources.base import register, Source, SOURCE_REGISTRY
from ainews.store import Store


@register("fake")
class _FakeSource(Source):
    """Test source that emits items from its options, no network."""

    def fetch(self) -> list[RawItem]:
        out = []
        for spec in self.options.get("items", []):
            out.append(RawItem(
                source_id=self.id,
                url=spec["url"],
                title=spec["title"],
                summary=spec.get("summary", ""),
                metadata={"source_weight": self.weight},
            ))
        return out


@register("boom")
class _BoomSource(Source):
    def fetch(self) -> list[RawItem]:
        raise RuntimeError("feed down")


def _cfg(id, items, weight=1.0):
    return SourceConfig(id=id, type="fake", weight=weight, options={"items": items})


def test_end_to_end_run(tmp_path, scope):
    sources = [
        _cfg("relevant-src", [
            {"url": "https://a.com/1", "title": "Acme launches new large language model API",
             "summary": "framework now available"},
        ], weight=2.0),
        _cfg("noise-src", [
            {"url": "https://a.com/2", "title": "Opinion: top 10 AI podcast picks",
             "summary": "a podcast opinion"},
        ]),
        _cfg("dupe-src", [
            # Same URL as relevant-src item -> within-batch duplicate.
            {"url": "https://a.com/1?utm_source=x", "title": "Acme launches new large language model API"},
        ]),
    ]
    with Store(tmp_path / "t.db") as store:
        report = run(scope, sources, store)
        assert report.fetched == 3
        assert report.duplicates == 1
        assert report.unique == 2
        assert report.relevant == 1
        assert report.irrelevant == 1
        assert store.count("relevant") == 1


def test_source_error_isolated(tmp_path, scope):
    sources = [
        SourceConfig(id="broken", type="boom"),
        _cfg("ok", [{"url": "https://a.com/x", "title": "New framework releases",
                     "summary": "large language model"}], weight=2.0),
    ]
    with Store(tmp_path / "t.db") as store:
        report = run(scope, sources, store)
        assert "broken" in report.source_errors
        assert report.fetched == 1  # ok source still ran


def test_second_run_dedupes_across_runs(tmp_path, scope):
    items = [{"url": "https://a.com/1", "title": "Acme launches large language model API",
              "summary": "framework now available"}]
    sources = [_cfg("s", items, weight=2.0)]
    with Store(tmp_path / "t.db") as store:
        r1 = run(scope, sources, store)
        assert r1.unique == 1
        r2 = run(scope, sources, store)  # same items again
        assert r2.duplicates == 1
        assert r2.unique == 0
