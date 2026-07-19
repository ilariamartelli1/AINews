"""Claude-backed summarizer (Anthropic API).

Produces the article via a single structured-output Messages request: the model
returns JSON constrained to the article schema (what changed / why it matters /
comparison), which we map straight onto an ``ArticleDraft``. Reads the API key
from the environment (``ANTHROPIC_API_KEY`` or an ``ant`` profile).

Kept as a thin single-call summarization step — no tools, no thinking — because
each article is short and this runs at volume. Model is configurable
(``summarizer.yaml``); the orchestrator falls back to the extractive engine if a
request fails, so a bad key or rate limit never blocks the run.
"""

from __future__ import annotations

import json
import logging

from ..article import ArticleDraft
from .base import Summarizer, SummaryInput, register

log = logging.getLogger("ainews.summarize.llm")

_SYSTEM = """You are the editor of a tightly-focused AI news blog. You write very short, \
concrete posts about practical AI developments (new models, tools, frameworks, features, \
paradigms) for readers who want signal, not commentary.

For each item, produce:
- what_changed: 2-4 sentences stating precisely what is new. Concrete and specific; no hype, \
no filler, no "in today's fast-moving AI landscape".
- why_it_matters: 1-3 sentences on the practical significance for builders.
- comparison: if related prior items are provided, 1-3 sentences framing this against them \
(what's different, better, or newly possible). If none are provided or none are relevant, \
return an empty string.

Be accurate to the source. Do not invent facts, versions, benchmarks, or quotes. If the \
source is thin, keep the post short rather than padding it."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "what_changed": {"type": "string"},
        "why_it_matters": {"type": "string"},
        "comparison": {"type": "string"},
    },
    "required": ["what_changed", "why_it_matters", "comparison"],
    "additionalProperties": False,
}


@register("llm")
class LLMSummarizer(Summarizer):
    def __init__(self, config) -> None:
        super().__init__(config)
        self._client = None  # lazily created so importing the module needs no key

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()  # resolves key from env / ant profile
        return self._client

    def summarize(self, inp: SummaryInput) -> ArticleDraft:
        client = self._get_client()
        prompt = self._build_prompt(inp)

        response = client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )

        if response.stop_reason == "refusal":
            raise RuntimeError("model refused to summarize this item")

        text = next((b.text for b in response.content if b.type == "text"), "")
        data = json.loads(text)  # output_config guarantees schema-valid JSON

        draft = ArticleDraft(
            title=inp.title,
            what_changed=data["what_changed"].strip(),
            why_it_matters=data["why_it_matters"].strip(),
            comparison=data["comparison"].strip(),
            engine=self.type,
            model=self.config.model,
        )
        draft.assemble_body()
        return draft

    @staticmethod
    def _build_prompt(inp: SummaryInput) -> str:
        parts = [f"TITLE: {inp.title}", f"SOURCE URL: {inp.url}"]
        if inp.scope_name:
            parts.append(f"BLOG FOCUS: {inp.scope_name}")
        body = inp.best_text()
        if body:
            parts += ["", "SOURCE TEXT:", body[:12000]]  # cap tokens
        if inp.related:
            parts += ["", "RELATED PRIOR ITEMS (for the comparison section):"]
            for r in inp.related:
                line = f"- {r.title}"
                if r.summary:
                    line += f" — {r.summary[:200]}"
                parts.append(line)
        else:
            parts += ["", "RELATED PRIOR ITEMS: none"]
        return "\n".join(parts)
