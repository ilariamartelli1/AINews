from ainews.article import Article, SourceRef, ComparisonLink
from ainews.store import Store
from tests.conftest import make_item


def _relevant(title, url):
    it = make_item(title, summary="a large language model framework", url=url)
    it.status = "relevant"
    return it


def test_relevant_without_article_and_insert(tmp_path):
    with Store(tmp_path / "t.db") as store:
        it = _relevant("Model X launches", "https://x.com/1")
        store.insert_item(it)
        item_id = store.recent(status="relevant")[0]["id"]

        pending = store.relevant_without_article()
        assert len(pending) == 1

        article = Article(
            item_id=item_id, title="Model X launches",
            what_changed="It launched.", why_it_matters="Useful.",
            sources=[SourceRef(url="https://x.com/1", title="Model X", is_primary=True)],
            comparisons=[ComparisonLink(related_item_id=None, related_title="Model W",
                                        related_url="https://x.com/w", similarity=0.3)],
            quality_status="pass",
        )
        aid = store.insert_article(article)
        assert aid > 0

        # No longer pending once it has an article.
        assert store.relevant_without_article() == []
        assert store.count_articles() == 1
        assert store.count_articles("pass") == 1

        got = store.get_article(aid)
        assert got["title"] == "Model X launches"
        assert len(got["sources"]) == 1
        assert got["sources"][0]["is_primary"] == 1
        assert len(got["comparisons"]) == 1


def test_content_caching(tmp_path):
    with Store(tmp_path / "t.db") as store:
        it = _relevant("Item", "https://x.com/c")
        store.insert_item(it)
        store.set_item_content(it.url_fingerprint, "full extracted body text")
        row = store.recent(status="relevant")[0]
        assert row["content"] == "full extracted body text"
        assert row["content_fetched_at"]


def test_one_article_per_item(tmp_path):
    import pytest
    with Store(tmp_path / "t.db") as store:
        it = _relevant("Item", "https://x.com/d")
        store.insert_item(it)
        item_id = store.recent(status="relevant")[0]["id"]
        art = Article(item_id=item_id, title="t", what_changed="w", why_it_matters="y",
                      sources=[SourceRef(url="https://x.com/d")])
        store.insert_article(art)
        with pytest.raises(Exception):
            store.insert_article(art)  # duplicate item_id -> UNIQUE violation
