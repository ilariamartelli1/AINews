from ainews.config import SummarizerConfig
from ainews.generate import generate
from ainews.store import Store
from tests.conftest import make_item


def _relevant(title, summary, url):
    it = make_item(title, summary=summary, url=url)
    it.status = "relevant"
    return it


def _extractive_cfg():
    # Offline: extractive engine, no page fetching.
    return SummarizerConfig(type="extractive", fetch_full_page=False,
                            min_words=10, max_words=400,
                            compare_top_k=3, compare_min_similarity=0.05)


def test_generate_creates_articles_with_sources(tmp_path, scope):
    with Store(tmp_path / "t.db") as store:
        store.insert_item(_relevant(
            "Acme launches a new open-source large language model",
            "Acme launched a new open-source large language model. It ships with a "
            "Python SDK and a large context window for developers building agents.",
            "https://a.com/1"))
        report = generate(scope, _extractive_cfg(), store, limit=10)

        assert report.considered == 1
        assert report.generated == 1
        art = store.recent_articles()[0]
        full = store.get_article(art["id"])
        assert full["sources"], "primary source must be attached"
        assert full["sources"][0]["is_primary"] == 1
        assert scope.name in full["scope_tags"]
        assert full["body"]


def test_generate_populates_comparison_links(tmp_path, scope):
    with Store(tmp_path / "t.db") as store:
        # A prior relevant item, similar topic.
        store.insert_item(_relevant(
            "Beta ships an open-source large language model",
            "Beta shipped an open-source large language model with a Python SDK and "
            "a big context window for developers.",
            "https://b.com/1"))
        # The candidate, topically related to the prior.
        store.insert_item(_relevant(
            "Acme releases an open-source large language model",
            "Acme released an open-source large language model with a Python SDK and "
            "a large context window aimed at developers building agents.",
            "https://a.com/1"))

        report = generate(scope, _extractive_cfg(), store, limit=10)
        assert report.generated == 2

        # At least one article should link to the other as a comparison.
        linked = 0
        for a in store.recent_articles():
            full = store.get_article(a["id"])
            linked += len(full["comparisons"])
        assert linked >= 1


def test_generate_is_idempotent(tmp_path, scope):
    with Store(tmp_path / "t.db") as store:
        store.insert_item(_relevant(
            "New agent framework released",
            "A new agent framework was released with an SDK and plugin system for tools.",
            "https://a.com/x"))
        r1 = generate(scope, _extractive_cfg(), store, limit=10)
        assert r1.generated == 1
        r2 = generate(scope, _extractive_cfg(), store, limit=10)
        assert r2.considered == 0  # already has an article
        assert r2.generated == 0
        assert store.count_articles() == 1
