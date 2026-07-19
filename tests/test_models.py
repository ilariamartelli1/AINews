from ainews.models import normalize_url, normalize_title, RawItem


def test_normalize_url_strips_tracking_and_trailing_slash():
    a = normalize_url("https://www.Example.com/Post/?utm_source=twitter&id=5")
    b = normalize_url("https://example.com/Post?id=5")
    assert a == b  # scheme/www/tracking normalized away; kept param preserved


def test_normalize_url_drops_fragment():
    assert normalize_url("https://x.com/a#section") == normalize_url("https://x.com/a")


def test_normalize_title_lowercases_and_strips_punctuation():
    assert normalize_title("OpenAI Launches GPT-9!!!") == "openai launches gpt 9"


def test_fingerprints_match_for_equivalent_items():
    i1 = RawItem(source_id="a", url="https://www.x.com/p?utm_source=x", title="Big Model!")
    i2 = RawItem(source_id="b", url="https://x.com/p", title="big model")
    assert i1.url_fingerprint == i2.url_fingerprint
    assert i1.title_fingerprint == i2.title_fingerprint
