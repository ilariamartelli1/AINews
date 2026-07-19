from ainews.dedup import dedupe_within_batch, dedupe
from ainews.store import Store
from tests.conftest import make_item


def test_within_batch_same_url_collapsed():
    a = make_item("Title A", url="https://x.com/p?utm_source=a", source_id="s1", weight=1.0)
    b = make_item("Different title", url="https://www.x.com/p", source_id="s2", weight=2.0)
    kept, dupes = dedupe_within_batch([a, b])
    assert len(kept) == 1
    assert len(dupes) == 1
    # Higher-weight source (s2) wins.
    assert kept[0].source_id == "s2"


def test_within_batch_same_title_collapsed():
    a = make_item("Big Model Released", url="https://x.com/a", weight=1.0)
    b = make_item("big model released", url="https://y.com/b", weight=0.5)
    kept, dupes = dedupe_within_batch([a, b])
    assert len(kept) == 1
    assert dupes[0].status == "duplicate"


def test_cross_run_dedup_against_store(tmp_path):
    db = tmp_path / "t.db"
    with Store(db) as store:
        first = make_item("Model X launches", url="https://x.com/model-x")
        store.insert_item(first)

        # Same URL again in a new batch -> duplicate.
        again = make_item("Model X launches", url="https://x.com/model-x?utm_source=rss")
        res = dedupe([again], store)
        assert len(res.unique) == 0
        assert len(res.duplicates) == 1


def test_cross_run_new_item_survives(tmp_path):
    db = tmp_path / "t.db"
    with Store(db) as store:
        store.insert_item(make_item("Old news", url="https://x.com/old"))
        res = dedupe([make_item("Fresh news", url="https://x.com/fresh")], store)
        assert len(res.unique) == 1
        assert len(res.duplicates) == 0
