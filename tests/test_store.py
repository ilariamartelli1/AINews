from ainews.store import Store
from tests.conftest import make_item


def test_insert_and_ignore_duplicate(tmp_path):
    with Store(tmp_path / "t.db") as store:
        item = make_item("Hello", url="https://x.com/a")
        assert store.insert_item(item) is True
        # Same url fingerprint -> ignored, no raise.
        again = make_item("Hello again", url="https://www.x.com/a?utm_source=z")
        assert store.insert_item(again) is False
        assert store.count() == 1


def test_seen_fingerprints(tmp_path):
    with Store(tmp_path / "t.db") as store:
        a = make_item("A", url="https://x.com/a")
        store.insert_item(a)
        seen = store.seen_url_fingerprints([a.url_fingerprint, "deadbeef"])
        assert a.url_fingerprint in seen
        assert "deadbeef" not in seen


def test_counts_by_status(tmp_path):
    with Store(tmp_path / "t.db") as store:
        r = make_item("relevant one", url="https://x.com/1"); r.status = "relevant"
        i = make_item("irrelevant one", url="https://x.com/2"); i.status = "irrelevant"
        store.insert_items([r, i])
        assert store.count("relevant") == 1
        assert store.count("irrelevant") == 1
        assert store.count() == 2


def test_run_bookkeeping(tmp_path):
    with Store(tmp_path / "t.db") as store:
        rid = store.start_run()
        store.finish_run(rid, {"fetched": 3})
        row = store.conn.execute("SELECT stats FROM runs WHERE id=?", (rid,)).fetchone()
        assert '"fetched": 3' in row[0]
