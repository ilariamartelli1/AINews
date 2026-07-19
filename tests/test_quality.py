from ainews.article import ArticleDraft, SourceRef
from ainews.quality import check_article


def _draft(**kw):
    d = ArticleDraft(
        title=kw.get("title", "New framework released"),
        what_changed=kw.get("what_changed", "Acme released a new agent framework. "
                            "It ships with a Python SDK and a plugin system for tools. "
                            "The framework targets local and hosted models alike."),
        why_it_matters=kw.get("why_it_matters", "It lowers the barrier to building agents."),
        comparison=kw.get("comparison", ""),
    )
    d.sources = kw.get("sources", [SourceRef(url="https://x.com/a", title="t", is_primary=True)])
    return d


def test_good_article_passes():
    r = check_article(_draft(), min_words=10, max_words=320)
    assert r.status == "pass"
    assert r.ok_to_publish


def test_missing_sources_fails():
    r = check_article(_draft(sources=[]))
    assert r.status == "fail"
    assert "missing sources" in r.issues
    assert not r.ok_to_publish


def test_too_short_fails():
    r = check_article(_draft(what_changed="Tiny.", why_it_matters=""), min_words=40)
    assert r.status == "fail"
    assert any("too short" in i for i in r.issues)


def test_refusal_text_fails():
    r = check_article(_draft(what_changed="I cannot summarize this content for you at all "
                             "because it is unavailable and I am sorry about that situation."))
    assert r.status == "fail"
    assert any("placeholder" in i for i in r.issues)


def test_missing_comparison_flags_when_required():
    r = check_article(_draft(comparison=""), min_words=10, require_comparison=True)
    assert r.status == "flagged"
    assert "missing comparison section" in r.issues
