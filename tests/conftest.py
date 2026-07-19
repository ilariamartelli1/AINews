import pytest

from ainews.config import ScopeConfig
from ainews.models import RawItem


@pytest.fixture
def scope() -> ScopeConfig:
    return ScopeConfig.from_dict({
        "name": "test-scope",
        "strong_keywords": ["large language model", "framework", "api", "model"],
        "normal_keywords": ["ai", "tool"],
        "announcement_signals": ["launches", "introduces", "releases", "now available"],
        "exclude_keywords": ["opinion", "podcast", "top 10"],
        "scoring": {
            "strong_keyword": 3.0,
            "normal_keyword": 1.0,
            "announcement_signal": 2.0,
            "exclude_penalty": 4.0,
            "source_weight_scale": 1.0,
            "min_score": 4.0,
        },
    })


def make_item(title: str, summary: str = "", url: str = "https://example.com/a",
              source_id: str = "s1", weight: float = 1.0) -> RawItem:
    return RawItem(
        source_id=source_id,
        url=url,
        title=title,
        summary=summary,
        metadata={"source_weight": weight},
    )
