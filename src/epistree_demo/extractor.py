"""KnowledgeExtractor — single-pass structured extraction via Instructor.

Uses FlatGraphBundle (flat nodes + relations) as the LLM-facing schema,
then converts to the canonical GraphBundle.  This avoids forcing the model
to pre-sort nodes into questions/claims/events arrays.

Matches section 5.5 of DEMO_DESIGN.md.
"""

from __future__ import annotations

import json
from typing import Any

import instructor
from openai import OpenAI

from .config import settings
from .models import (
    FlatGraphBundle,
    GraphBundle,
    SearchItem,
    flat_to_graph_bundle,
    validate_quote,
)

EXTRACTION_PROMPT_SYSTEM = """你只能根据输入中的知乎来源文本提取信息。
不得用你的先验知识补充人物、时间、事件或因果关系。
每个节点和关系必须引用至少一个输入 source_id。
证据不足时少输出，不要猜测。

输出格式：一个 JSON 对象，包含 topic (string), nodes (array), relations (array)。
- nodes: 每个元素有 id, type (question|claim|event), text, source_ids (至少一个), 
         question_id (type=claim 时需要), occurred_at (type=event 时可选), 
         confidence (0-1, 非 claim 事件节点可选)
- relations: 每个元素有 id, source_node_id, target_node_id (必须都是 claim 节点), 
            relation_type (supports|contradicts|evolves_into), source_ids (至少一个),
            confidence (0-1)
"""


class KnowledgeExtractor:
    """Single-shot structured knowledge extractor.

    Uses Instructor to enforce FlatGraphBundle schema with limited retries.
    """

    def __init__(self) -> None:
        if not settings.has_llm_auth:
            raise RuntimeError("LLM_API_KEY not configured")

        self.client = instructor.from_openai(
            OpenAI(
                base_url=str(settings.llm_base_url),
                api_key=settings.llm_api_key,
            ),
            mode=instructor.Mode.JSON_SCHEMA,
        )
        self.model = settings.llm_model

    def extract(
        self,
        topic: str,
        sources: list[SearchItem],
        max_retries: int = 2,
    ) -> GraphBundle:
        """Perform a single extraction call.

        Returns validated GraphBundle or raises on repeated failure.
        """
        source_inputs = self._build_source_inputs(sources)
        user_prompt = self._build_user_prompt(topic, source_inputs)

        try:
            flat = self.client.chat.completions.create(
                model=self.model,
                response_model=FlatGraphBundle,
                max_retries=max_retries,
                messages=[
                    {"role": "system", "content": EXTRACTION_PROMPT_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
            )
        except Exception as exc:
            raise RuntimeError(f"MODEL_VALIDATION_FAILED: {exc}") from exc

        # Convert flat → canonical
        bundle = flat_to_graph_bundle(flat)

        # Post-process: validate quotes against actual content text
        source_text_map = {s.source_id: s.content_text for s in sources}
        self._clean_quotes(bundle, source_text_map)

        return bundle

    # ── internals ───────────────────────────────────────────────────

    def _build_source_inputs(self, sources: list[SearchItem]) -> list[dict[str, Any]]:
        """Build the per-source dict for the model prompt.

        Only fields listed in section 9.2 of DEMO_DESIGN.md.
        """
        inputs = []
        for s in sources:
            text = s.content_text[:1500] if s.content_text else ""
            truncated = len(s.content_text) > 1500 if s.content_text else False
            inputs.append({
                "source_id": s.source_id,
                "title": s.title,
                "author_name": s.author_name,
                "edit_time": s.edit_time.isoformat() if s.edit_time else None,
                "content_text": text,
                "truncated_for_model": truncated,
            })
        return inputs

    def _build_user_prompt(self, topic: str, source_inputs: list[dict]) -> str:
        return json.dumps(
            {
                "topic": topic,
                "sources": source_inputs,
                "instruction": (
                    f"Extract a knowledge graph from the above {len(source_inputs)} "
                    "Zhihu sources about the topic. Return a FlatGraphBundle with "
                    "nodes (type=question|claim|event) and relations between claims."
                ),
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _clean_quotes(bundle: GraphBundle, source_text_map: dict[str, str]) -> None:
        """Drop invalid quotes that cannot be found in the source text."""
        for q in bundle.questions:
            q.source_refs = [validate_quote(r, source_text_map.get(r.source_id, "")) for r in q.source_refs]
        for c in bundle.claims:
            c.source_refs = [validate_quote(r, source_text_map.get(r.source_id, "")) for r in c.source_refs]
        for e in bundle.events:
            e.source_refs = [validate_quote(r, source_text_map.get(r.source_id, "")) for r in e.source_refs]
        for r in bundle.relations:
            r.source_refs = [validate_quote(r, source_text_map.get(r.source_id, "")) for r in r.source_refs]
