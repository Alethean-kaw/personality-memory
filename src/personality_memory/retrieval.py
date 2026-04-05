from __future__ import annotations

from .backends import SimilarityBackend, get_backend
from .lifecycle import DEFAULT_AGING_POLICY, apply_memory_lifecycle, memory_policy_description
from .models import LongTermMemory, RetrievalHit, RetrievalResult, ReviewItem
from .persona_builder import PersonaBuilder
from .scoring import effective_persona_confidence
from .storage import SCHEMA_VERSION
from .utils import clamp, sentence_excerpt, sort_timestamp, utc_now


DEFAULT_USAGE_GUIDANCE = [
    "Treat Relevant Long-Term Memory as durable guidance grounded in prior interaction.",
    "Treat contested signals and open review items as uncertain; do not present them as confirmed facts.",
    "Use this context to adapt responses, not to rewrite memory state automatically.",
    "Call this contract before generating a final answer when long-term personalization matters.",
]


class RetrievalService:
    def __init__(
        self,
        *,
        backend_name: str = "hybrid",
        backend: SimilarityBackend | None = None,
        contested_threshold: int = 2,
        aging_policy: str = DEFAULT_AGING_POLICY,
    ) -> None:
        self.backend = backend or get_backend(backend_name)
        self.contested_threshold = contested_threshold
        self.aging_policy = aging_policy
        self.persona_builder = PersonaBuilder(contested_threshold=contested_threshold, aging_policy=aging_policy)

    def retrieve(
        self,
        *,
        query: str,
        memories: list[LongTermMemory],
        review_items: list[ReviewItem] | None = None,
        profile_id: str = "default",
        top_k: int = 5,
        include_contested: bool = True,
        include_review: bool = True,
        reference_time: str | None = None,
    ) -> RetrievalResult:
        reference = reference_time or utc_now()
        for memory in memories:
            apply_memory_lifecycle(memory, reference_time=reference, aging_policy=self.aging_policy)

        profile = self.persona_builder.build(memories, reference_time=reference)
        active_memories = [memory for memory in memories if memory.active and memory.lifecycle_state == "active"]
        stable_memories = [memory for memory in active_memories if memory.contradiction_count < self.contested_threshold]

        hits = [self._build_hit(query, memory) for memory in stable_memories]
        hits.sort(key=lambda item: (-item.relevance_score, -item.effective_confidence, -item.confidence, item.memory_id))

        open_reviews = []
        if include_review:
            open_reviews = sorted(
                [item for item in review_items or [] if item.status == "open"],
                key=lambda item: (sort_timestamp(item.opened_at), item.id),
            )

        contested_signals = profile.contested_signals if include_contested else []
        return RetrievalResult(
            schema_version=SCHEMA_VERSION,
            profile_id=profile_id,
            query=query,
            generated_at=reference,
            memory_hits=hits[: max(0, top_k)],
            persona_adaptation_notes=profile.system_adaptation_notes,
            contested_signals=contested_signals,
            open_reviews=open_reviews,
            usage_guidance=list(DEFAULT_USAGE_GUIDANCE),
            memory_policy=memory_policy_description(self.aging_policy),
        )

    def render_markdown(
        self,
        result: RetrievalResult,
        *,
        include_contested: bool = True,
        include_review: bool = True,
    ) -> str:
        lines = [
            "# Retrieved Context",
            "",
            f"- Schema version: {result.schema_version}",
            f"- Profile: {result.profile_id}",
            f"- Query: {result.query}",
            "",
            "## Relevant Long-Term Memory",
        ]
        if result.memory_hits:
            for hit in result.memory_hits:
                evidence = "; ".join(hit.supporting_evidence[:2]) if hit.supporting_evidence else "No evidence excerpts stored."
                lines.append(
                    f"- [{hit.memory_id}] ({hit.category}) {hit.summary} | relevance={hit.relevance_score:.2f} | effective_confidence={hit.effective_confidence:.2f} | evidence: {evidence}"
                )
        else:
            lines.append("- No stable long-term memories matched the query.")

        lines.extend(["", "## Persona Adaptation Notes"])
        if result.persona_adaptation_notes:
            for note in result.persona_adaptation_notes:
                refs = ", ".join(note.get("memory_refs", []))
                lines.append(f"- {note['note']} (refs: {refs})")
        else:
            lines.append("- No adaptation notes available.")

        lines.extend(["", "## Contested / Uncertain Signals"])
        if include_contested:
            if result.contested_signals:
                for signal in result.contested_signals:
                    effective = signal.effective_confidence if signal.effective_confidence is not None else signal.confidence
                    lines.append(
                        f"- {signal.summary} (id: {signal.memory_id}, confidence={signal.confidence:.2f}, effective_confidence={effective:.2f}, contradictions={signal.contradiction_count})"
                    )
            else:
                lines.append("- No contested memories matched or exist right now.")
        else:
            lines.append("- Contested memories were excluded by command option.")

        lines.extend(["", "## Open Review Items"])
        if include_review:
            if result.open_reviews:
                for item in result.open_reviews:
                    target = item.target_memory_id or "(new memory candidate)"
                    lines.append(
                        f"- [{item.id}] candidate={item.candidate_id} target={target} kind={item.kind} reason={item.reason}"
                    )
            else:
                lines.append("- No open review items.")
        else:
            lines.append("- Open review items were excluded by command option.")

        lines.extend(["", "## Usage Guidance"])
        for line in result.usage_guidance:
            lines.append(f"- {line}")
        return "\n".join(lines)

    def _build_hit(self, query: str, memory: LongTermMemory) -> RetrievalHit:
        summary_score = self.backend.similarity(query, memory.summary)
        evidence_pairs = []
        for ref in memory.evidence:
            score = self.backend.similarity(query, ref.excerpt)
            evidence_pairs.append((score, sentence_excerpt(ref.excerpt, 120)))
        evidence_pairs.sort(key=lambda item: item[0], reverse=True)
        evidence_score = evidence_pairs[0][0] if evidence_pairs else 0.0
        base_similarity = max(summary_score, evidence_score * 0.94)
        confidence_boost = memory.confidence * 0.18
        reinforcement_boost = min(0.12, max(0, memory.reinforcement_count - 1) * 0.02)
        category_boost = 0.04 if any(token in memory.category for token in ("style", "project", "preference", "constraint")) else 0.0
        contradiction_penalty = min(0.18, memory.contradiction_count * 0.05)
        relevance = clamp((base_similarity * 0.66) + confidence_boost + reinforcement_boost + category_boost - contradiction_penalty, 0.0, 0.99)
        return RetrievalHit(
            memory_id=memory.id,
            summary=memory.summary,
            category=memory.category,
            confidence=memory.confidence,
            effective_confidence=effective_persona_confidence(memory.confidence, memory.contradiction_count),
            relevance_score=relevance,
            supporting_evidence=[excerpt for _, excerpt in evidence_pairs[:2]],
        )
