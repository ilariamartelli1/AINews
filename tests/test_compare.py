from ainews.compare import find_related


def _item(id, title, summary, url):
    return {"id": id, "title": title, "summary": summary, "url": url}


def test_finds_topically_related_prior():
    candidate = _item(None, "Acme releases a new open-source large language model",
                      "A transformer model for developers with a big context window.", "u0")
    priors = [
        _item(1, "Beta ships an open-source large language model",
              "A transformer model with a large context window for developers.", "u1"),
        _item(2, "A recipe for banana bread",
              "Flour, sugar, bananas and butter make a loaf.", "u2"),
    ]
    related = find_related(candidate, priors, top_k=3, min_similarity=0.05)
    assert related, "expected at least one related item"
    assert related[0].related_id == 1  # the LLM item, not the banana bread
    assert related[0].similarity > 0


def test_threshold_filters_unrelated():
    candidate = _item(None, "New diffusion model for image generation",
                      "text to image diffusion", "u0")
    priors = [_item(1, "Quarterly tax filing tips", "accounting deadlines forms", "u1")]
    assert find_related(candidate, priors, min_similarity=0.2) == []


def test_empty_priors():
    assert find_related({"title": "x", "summary": "y"}, []) == []
