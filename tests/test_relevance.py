from ainews.relevance import score_item, apply_relevance
from tests.conftest import make_item


def test_concrete_announcement_is_relevant(scope):
    item = make_item(
        "Acme launches new large language model API",
        "A framework for developers, now available.",
        weight=2.0,
    )
    res = score_item(item, scope)
    assert res.relevant
    assert res.score >= scope.scoring.min_score
    assert res.signal_hits  # novelty markers detected


def test_generic_commentary_is_dropped(scope):
    item = make_item(
        "Opinion: the top 10 AI podcast episodes",
        "A podcast opinion piece.",
        weight=0.5,
    )
    res = score_item(item, scope)
    assert not res.relevant
    assert res.exclude_hits


def test_no_in_scope_signal_dropped_even_if_score_ok(scope):
    # Only 'normal' keywords, no strong/announcement -> not relevant.
    item = make_item("An AI tool", "ai tool ai tool", weight=3.0)
    res = score_item(item, scope)
    assert not res.relevant


def test_word_boundary_avoids_false_substring_match(scope):
    # "api" must not match inside "therapist"; no strong keyword should hit.
    item = make_item("The therapist chair", "captain said maintain", weight=0.0)
    res = score_item(item, scope)
    assert "api" not in res.strong_hits


def test_apply_relevance_mutates_item(scope):
    item = make_item("New framework releases today", "large language model", weight=2.0)
    apply_relevance(item, scope)
    assert item.status == "relevant"
    assert item.relevance_score > 0
    assert item.relevance_reasons
