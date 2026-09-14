"""All Pydantic data contracts for Epistree Demo.

Matches section 6 of DEMO_DESIGN.md.

Two layers:
  - FlatGraphBundle: what the LLM naturally produces (flat nodes + relations)
  - GraphBundle: fully validated canonical form with separate question/claim/event arrays
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Mapping

from pydantic import BaseModel, Field, HttpUrl, model_validator

# ── helper ────────────────────────────────────────────────────────────────

def _generate_source_id(content_type: str, content_id: str) -> str:
    return f"zhihu:{content_type}:{content_id}"


# ── 6.1 知乎搜索对象 ──────────────────────────────────────────────────────

class SearchItem(BaseModel):
    """A single item from the Zhihu search API response."""

    source_id: str = ""
    content_id: str
    content_type: str
    title: str
    content_text: str
    url: HttpUrl
    author_name: str
    edit_time: datetime | None = None
    vote_up_count: int = 0
    comment_count: int = 0
    authority_level: str | None = None
    ranking_score: float | None = None

    def model_post_init(self, __context) -> None:
        if not self.source_id:
            self.source_id = _generate_source_id(self.content_type, self.content_id)


class SearchResponse(BaseModel):
    """Wrapper around the raw zhihu_search API response."""

    code: int
    data: list[SearchItem] = Field(default_factory=list)
    search_hash_id: str | None = None
    raw_json: dict | None = None


class QuotaResponse(BaseModel):
    """Response from the Zhihu quota endpoint.

    Actual API shape:
    {"Code": 0, "Message": "success", "Data": [{"APIID": "zhihu_search", "TotalQuota": 5000, "TotalUsed": 1, "RemainingQuota": 4999}]}
    """

    code: int = 0
    daily_total: int = 5000
    used: int = 0
    remaining: int = 0
    reset_at: datetime | None = None


# ── FlatGraphBundle: LLM-friendly intermediate schema ─────────────────────
# The model naturally outputs nodes as a flat list with a type discriminator,
# not pre-split into questions/claims/events.

class FlatNode(BaseModel):
    """A single node in the flat representation."""
    id: str
    type: Literal["question", "claim", "event"]
    text: str
    question_id: str | None = None       # required for claim nodes
    occurred_at: str | None = None       # optional for event nodes
    source_ids: list[str] = Field(default_factory=list, min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)


class FlatRelation(BaseModel):
    """A relation between two claim nodes."""
    id: str
    source_node_id: str
    target_node_id: str
    relation_type: Literal["supports", "contradicts", "evolves_into"]
    source_ids: list[str] = Field(default_factory=list, min_length=1)
    confidence: float = Field(default=0.5, ge=0, le=1)


class FlatGraphBundle(BaseModel):
    """LLM-friendly extraction output — flat node list + relation list.

    This is the ONLY schema sent to Instructor. It matches how models
    naturally think about graphs (nodes and edges), avoiding the need
    for them to separate questions/claims/events at generation time.
    """

    topic: str
    nodes: list[FlatNode] = Field(default_factory=list, max_length=400)      # Up to 30Q + 150C + 40E + 180S
    relations: list[FlatRelation] = Field(default_factory=list, max_length=250)

    @model_validator(mode="after")
    def _validate_flat(self) -> "FlatGraphBundle":
        errors: list[str] = []
        node_ids: set[str] = set()
        claim_ids: set[str] = set()

        for n in self.nodes:
            if n.id in node_ids:
                errors.append(f"Duplicate node id: {n.id}")
            node_ids.add(n.id)
            if n.type == "claim":
                claim_ids.add(n.id)
            if n.type == "question" and n.question_id:
                errors.append(f"Question {n.id} should not have question_id")

        for r in self.relations:
            if r.source_node_id not in claim_ids:
                errors.append(f"Relation {r.id}: source_node_id {r.source_node_id!r} is not a Claim")
            if r.target_node_id not in claim_ids:
                errors.append(f"Relation {r.id}: target_node_id {r.target_node_id!r} is not a Claim")
        relation_ids = [r.id for r in self.relations]
        errors.extend(
            f"Duplicate relation id: {rid}" for rid in set(relation_ids)
            if relation_ids.count(rid) > 1
        )
        question_ids = {n.id for n in self.nodes if n.type == "question"}
        for n in self.nodes:
            if n.type == "claim" and (not n.question_id or n.question_id not in question_ids):
                errors.append(f"Claim {n.id}: question_id {n.question_id!r} not found in nodes")

        if errors:
            raise ValueError("FlatGraphBundle validation failed:\n" + "\n".join(errors))
        return self


def flat_to_graph_bundle(flat: FlatGraphBundle) -> "GraphBundle":
    """Convert a FlatGraphBundle to the canonical GraphBundle form.

    This runs AFTER FlatGraphBundle validation, so cross-references are
    guaranteed valid.  GraphBundle model_validator also runs on the result
    as a defence-in-depth check.
    """
    questions: list[QuestionNode] = []
    claims: list[ClaimNode] = []
    events: list[EventNode] = []
    for n in flat.nodes:
        refs = [SourceRef(source_id=sid) for sid in n.source_ids]
        if n.type == "question":
            questions.append(QuestionNode(id=n.id, text=n.text, source_refs=refs))
        elif n.type == "claim":
            qid = n.question_id
            claims.append(ClaimNode(
                id=n.id, text=n.text, question_id=qid,
                source_refs=refs, confidence=n.confidence or 0.5,
            ))
        elif n.type == "event":
            events.append(EventNode(
                id=n.id, text=n.text, occurred_at=n.occurred_at,
                source_refs=refs, confidence=n.confidence or 0.5,
            ))

    # Enforce claim limit during conversion
    MAX_CLAIMS = 150
    claims = claims[:MAX_CLAIMS]
    claim_ids_in_bundle = {c.id for c in claims}

    relations = [
        CandidateRelation(
            id=r.id,
            source_node_id=r.source_node_id,
            target_node_id=r.target_node_id,
            relation_type=r.relation_type,
            source_refs=[SourceRef(source_id=sid) for sid in r.source_ids],
            confidence=r.confidence,
        )
        for r in flat.relations
        if r.source_node_id in claim_ids_in_bundle and r.target_node_id in claim_ids_in_bundle
    ]

    return GraphBundle(
        topic=flat.topic,
        questions=questions,
        claims=claims,
        events=events,
        relations=relations,
    )


# ── 6.2 知识对象 ──────────────────────────────────────────────────────────

class SourceRef(BaseModel):
    source_id: str
    quote: str | None = None


class QuestionNode(BaseModel):
    id: str
    text: str
    source_refs: list[SourceRef]


class ClaimNode(BaseModel):
    id: str
    text: str
    question_id: str
    source_refs: list[SourceRef]
    confidence: float = Field(ge=0, le=1)


class EventNode(BaseModel):
    id: str
    text: str
    occurred_at: str | None = None
    source_refs: list[SourceRef]
    confidence: float = Field(ge=0, le=1)


class CandidateRelation(BaseModel):
    id: str
    source_node_id: str
    target_node_id: str
    relation_type: Literal["supports", "contradicts", "evolves_into"]
    source_refs: list[SourceRef]
    confidence: float = Field(ge=0, le=1)


class GraphBundle(BaseModel):
    """Top-level output from the knowledge extractor."""

    topic: str
    questions: list[QuestionNode] = Field(default_factory=list, max_length=40)
    claims: list[ClaimNode] = Field(default_factory=list, max_length=150)
    events: list[EventNode] = Field(default_factory=list, max_length=50)
    relations: list[CandidateRelation] = Field(default_factory=list, max_length=250)

    # ── 6.3 跨对象校验 ──────────────────────────────────────────────────

    @model_validator(mode="after")
    def _validate_cross_references(self) -> "GraphBundle":
        errors: list[str] = []

        all_source_ids: set[str] = set()
        claim_ids: set[str] = {c.id for c in self.claims}
        question_ids: set[str] = {q.id for q in self.questions}

        # Collect source refs
        for q in self.questions:
            for r in q.source_refs:
                all_source_ids.add(r.source_id)
        for c in self.claims:
            for r in c.source_refs:
                all_source_ids.add(r.source_id)
        for e in self.events:
            for r in e.source_refs:
                all_source_ids.add(r.source_id)
        for r in self.relations:
            for sr in r.source_refs:
                all_source_ids.add(sr.source_id)

        # Claim.question_id must exist
        for c in self.claims:
            if c.question_id and c.question_id not in question_ids:
                errors.append(f"Claim {c.id}: question_id {c.question_id!r} does not exist")

        # Relation endpoints must be existing Claims
        for r in self.relations:
            if r.source_node_id not in claim_ids:
                errors.append(f"Relation {r.id}: source_node_id {r.source_node_id!r} is not a Claim ID")
            if r.target_node_id not in claim_ids:
                errors.append(f"Relation {r.id}: target_node_id {r.target_node_id!r} is not a Claim ID")

        # source_refs must be non-empty
        for q in self.questions:
            if not q.source_refs:
                errors.append(f"Question {q.id} has no source_refs")
        for c in self.claims:
            if not c.source_refs:
                errors.append(f"Claim {c.id} has no source_refs")
        for e in self.events:
            if not e.source_refs:
                errors.append(f"Event {e.id} has no source_refs")
        for r in self.relations:
            if not r.source_refs:
                errors.append(f"Relation {r.id} has no source_refs")

        if errors:
            raise ValueError("GraphBundle validation failed:\n" + "\n".join(errors))

        return self


# ── 6.3 quote 校验（独立工具函数） ────────────────────────────────────────

def validate_quote(ref: SourceRef, content_text: str) -> SourceRef:
    """If quote is non-empty but not found in source text, drop it.

    This is called after model extraction, not during Pydantic validation,
    because content_text is not in the GraphBundle.
    """
    if ref.quote and ref.quote not in content_text:
        return SourceRef(source_id=ref.source_id, quote=None)
    return ref


def validate_bundle_against_sources(
    bundle: GraphBundle, source_map: Mapping[str, SearchItem]
) -> GraphBundle:
    """Validate graph provenance against the exact sources supplied to the model.

    Pydantic validates shape; this domain check prevents fabricated source IDs,
    orphan questions and relations from entering storage or the UI.
    """
    errors: list[str] = []
    node_ids = [n.id for n in [*bundle.questions, *bundle.claims, *bundle.events]]
    relation_ids = [r.id for r in bundle.relations]
    if len(node_ids) != len(set(node_ids)):
        errors.append("Duplicate node id")
    if len(relation_ids) != len(set(relation_ids)):
        errors.append("Duplicate relation id")
    question_ids = {q.id for q in bundle.questions}
    claim_ids = {c.id for c in bundle.claims}
    for claim in bundle.claims:
        if claim.question_id not in question_ids:
            errors.append(f"Claim {claim.id}: unknown question_id {claim.question_id!r}")
    for obj in [*bundle.questions, *bundle.claims, *bundle.events, *bundle.relations]:
        for ref in obj.source_refs:
            source = source_map.get(ref.source_id)
            if source is None:
                errors.append(f"{getattr(obj, 'id', 'relation')}: unknown source_id {ref.source_id!r}")
            elif ref.quote and ref.quote not in source.content_text:
                # Keep the source reference but make unsupported quotes explicit.
                ref.quote = None
    for relation in bundle.relations:
        if relation.source_node_id not in claim_ids:
            errors.append(f"Relation {relation.id}: source endpoint is not a Claim")
        if relation.target_node_id not in claim_ids:
            errors.append(f"Relation {relation.id}: target endpoint is not a Claim")
    if errors:
        raise ValueError("MODEL_VALIDATION_FAILED: " + "; ".join(errors))
    return bundle
