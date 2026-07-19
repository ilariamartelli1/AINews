import json

from ainews.article import Article, SourceRef, ComparisonLink
from ainews.config import ScopeConfig
from ainews.site import SiteBuilder
from ainews.store import Store
from tests.conftest import make_item


def _seed(store: Store, title, url, status="pass", tags=None):
    it = make_item(title, summary="a large language model framework", url=url)
    it.status = "relevant"
    it.published_at = "2026-07-18T10:00:00+00:00"
    store.insert_item(it)
    item_id = store.recent(status="relevant")[0]["id"] if not tags else \
        [r for r in store.recent(status="relevant") if r["title"] == title][0]["id"]
    art = Article(
        item_id=item_id, title=title,
        what_changed="Acme launched a new open-source large language model with an SDK.",
        why_it_matters="It lowers the barrier for builders.",
        comparison="Compared to prior models it adds a bigger context window.",
        scope_tags=tags or ["Practical AI", "llm"],
        quality_status=status,
        sources=[SourceRef(url=url, title=title, source_id=it.source_id, is_primary=True)],
        comparisons=[ComparisonLink(related_item_id=None, related_title="Prior model",
                                    related_url="https://x.com/prior", similarity=0.42)],
    )
    store.insert_article(art)
    return item_id


def _scope():
    return ScopeConfig.from_dict({"name": "Test Blog", "description": "desc"})


def test_build_produces_all_pages(tmp_path):
    with Store(tmp_path / "t.db") as store:
        _seed(store, "Model X launches", "https://x.com/1")
        out = tmp_path / "site"
        stats = SiteBuilder(store, scope=_scope(), base_url="https://ex.com").build(out)

    assert stats["posts"] == 1
    for f in ["index.html", "archive.html", "search.json", "feed.xml", "feed.json",
              "posts/1.html", "static/style.css", "static/archive.js"]:
        assert (out / f).exists(), f"missing {f}"

    index = (out / "index.html").read_text()
    assert "Model X launches" in index
    assert "Test Blog" in index


def test_post_page_shows_sources_and_comparison(tmp_path):
    with Store(tmp_path / "t.db") as store:
        _seed(store, "Model X launches", "https://x.com/1")
        out = tmp_path / "site"
        SiteBuilder(store, scope=_scope()).build(out)

    post = (out / "posts" / "1.html").read_text()
    assert "Sources" in post
    assert "https://x.com/1" in post          # source reference exposed
    assert "What changed" in post
    assert "How it compares" in post
    assert "Prior model" in post              # comparison link


def test_failed_quality_not_published(tmp_path):
    with Store(tmp_path / "t.db") as store:
        _seed(store, "Good one", "https://x.com/ok", status="pass")
        _seed(store, "Bad one", "https://x.com/bad", status="fail")
        out = tmp_path / "site"
        stats = SiteBuilder(store, scope=_scope()).build(out)

    assert stats["posts"] == 1
    index = (out / "index.html").read_text()
    assert "Good one" in index
    assert "Bad one" not in index


def test_feeds_contain_post(tmp_path):
    with Store(tmp_path / "t.db") as store:
        _seed(store, "Model X launches", "https://x.com/1")
        out = tmp_path / "site"
        SiteBuilder(store, scope=_scope(), base_url="https://ex.com").build(out)

    feed_xml = (out / "feed.xml").read_text()
    assert "Model X launches" in feed_xml
    assert "https://ex.com/posts/1.html" in feed_xml  # base_url applied

    feed = json.loads((out / "feed.json").read_text())
    assert feed["version"].startswith("https://jsonfeed.org")
    assert feed["items"][0]["title"] == "Model X launches"


def test_search_index_shape(tmp_path):
    with Store(tmp_path / "t.db") as store:
        _seed(store, "Model X launches", "https://x.com/1")
        out = tmp_path / "site"
        SiteBuilder(store, scope=_scope()).build(out)

    idx = json.loads((out / "search.json").read_text())
    assert idx[0]["title"] == "Model X launches"
    assert idx[0]["source"]
    assert "text" in idx[0] and idx[0]["text"] == idx[0]["text"].lower()
