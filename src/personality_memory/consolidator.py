from __future__ import annotations

from dataclasses import dataclass, field

from .models import LongTermMemory, MemoryCandidate, RevisionEntry
from .scoring import contradiction_score, similarity_score
from .utils import clamp, stable_hash, utc_now


def memory_mutability(category: str) -> bool:
    return category not in {"identity"}


@dataclass(slots=True)
class ConsolidationResult:
    candidates: list[MemoryCandidate]
    memories: list[LongTermMemory]
    revisions: list[RevisionEntry] = field(default_factory=list)
    created: int = 0
    updated: int = 0
    conflicts: int = 0
    pending: int = 0


class MemoryConsolidator:
    def __init__(
        self,
        similarity_threshold: float = 0.74,
        promotion_threshold: float = 0.72,
        contradiction_threshold: float = 0.35,
    ) -> None:
        self.similarity_threshold = similarity_threshold
        self.promotion_threshold = promotion_threshold
        self.contradiction_threshold = contradiction_threshold

    def consolidate(
        self,
        candidates: list[MemoryCandidate],
        memories: list[LongTermMemory],
    ) -> ConsolidationResult:
        active_memories = [memory for memory in memories if memory.active]
        support_map = self._compute_candidate_support(candidates)
        revisions: list[RevisionEntry] = []
        created = 0
        updated = 0
        conflicts = 0
        pending = 0

        for candidate in sorted(candidates, key=lambda item: (item.created_at, -item.confidence)):
            if candidate.status in {"rejected", "outdated"}:
                continue

            best_match, best_similarity = self._best_match(candidate, active_memories)
            if best_match is not None:
                contradiction = contradiction_score(best_match.summary, candidate.content)
                if contradiction >= self.contradiction_threshold:
                    best_match.contradiction_count += 1
                    best_match.last_seen = max(best_match.last_seen, candidate.created_at)
                    candidate.status = "review"
                    candidate.notes = f"Potential contradiction with {best_match.id}"
                    conflicts += 1
                    revisions.append(
                        RevisionEntry(
                            id=f"rev_{stable_hash(f'conflict|{best_match.id}|{candidate.id}|{utc_now()}')}",
                            entity_type="long_term_memory",
                            entity_id=best_match.id,
                            action="conflict",
                            timestamp=utc_now(),
                            reason=f"Candidate {candidate.id} conflicts with memory {best_match.id}",
                            before=None,
                            after=best_match.to_dict(),
                        )
                    )
                    continue

                if best_similarity >= self.similarity_threshold:
                    before = best_match.to_dict()
                    self._merge_candidate(best_match, candidate)
                    candidate.status = "accepted"
                    candidate.notes = f"Merged into {best_match.id}"
                    updated += 1
                    revisions.append(
                        RevisionEntry(
                            id=f"rev_{stable_hash(f'reinforce|{best_match.id}|{candidate.id}|{utc_now()}')}",
                            entity_type="long_term_memory",
                            entity_id=best_match.id,
                            action="reinforce",
                            timestamp=utc_now(),
                            reason=f"Candidate {candidate.id} reinforced memory {best_match.id}",
                            before=before,
                            after=best_match.to_dict(),
                        )
                    )
                    continue

            support_count = support_map.get(candidate.id, 1)
            effective_confidence = clamp(candidate.confidence + max(0, support_count - 1) * 0.07, 0.0, 0.98)
            if effective_confidence >= self.promotion_threshold:
                memory = self._create_memory(candidate, effective_confidence)
                memories.append(memory)
                active_memories.append(memory)
                candidate.status = "accepted"
                candidate.notes = f"Promoted to {memory.id}"
                created += 1
                revisions.append(
                    RevisionEntry(
                        id=f"rev_{stable_hash(f'create|{memory.id}|{candidate.id}|{utc_now()}')}",
                        entity_type="long_term_memory",
                        entity_id=memory.id,
                        action="create",
                        timestamp=utc_now(),
                        reason=f"Candidate {candidate.id} promoted into long-term memory",
                        before=None,
                        after=memory.to_dict(),
                    )
                )
            else:
                candidate.status = "candidate"
                candidate.notes = f"Needs more evidence (support={support_count})"
                pending += 1

        return ConsolidationResult(
            candidates=candidates,
            memories=memories,
            revisions=revisions,
            created=created,
            updated=updated,
            conflicts=conflicts,
            pending=pending,
        )

    def _compute_candidate_support(self, candidates: list[MemoryCandidate]) -> dict[str, int]:
        support = {candidate.id: 1 for candidate in candidates}
        for index, candidate in enumerate(candidates):
            for other in candidates[index + 1 :]:
                if candidate.type != other.type:
                    continue
                if similarity_score(candidate.content, other.content) >= self.similarity_threshold:
                    support[candidate.id] += 1
                    support[other.id] += 1
        return support

    def _best_match(
        self,
        candidate: MemoryCandidate,
        memories: list[LongTermMemory],
    ) -> tuple[LongTermMemory | None, float]:
        best_memory: LongTermMemory | None = None
        best_similarity = 0.0
        for memory in memories:
            if memory.category != candidate.type:
                continue
            score = similarity_score(memory.summary, candidate.content)
            if score > best_similarity:
                best_similarity = score
                best_memory = memory
        return best_memory, best_similarity

    def _merge_candidate(self, memory: LongTermMemory, candidate: MemoryCandidate) -> None:
        memory.summary = self._prefer_more_informative_summary(memory.summary, candidate.content)
        memory.last_seen = max(memory.last_seen, candidate.created_at)
        memory.confidence = clamp(max(memory.confidence, candidate.confidence) + 0.04, 0.0, 0.99)
        memory.reinforcement_count += 1
        evidence_index = {item.conversation_event_id for item in memory.evidence}
        for ref in candidate.source_refs:
            if ref.conversation_event_id not in evidence_index:
                memory.evidence.append(ref)
                evidence_index.add(ref.conversation_event_id)

    def _create_memory(self, candidate: MemoryCandidate, confidence: float) -> LongTermMemory:
        memory_id = f"ltm_{stable_hash(f'{candidate.type}|{candidate.content}')}"
        return LongTermMemory(
            id=memory_id,
            summary=candidate.content,
            category=candidate.type,
            evidence=list(candidate.source_refs),
            confidence=confidence,
            first_seen=candidate.created_at,
            last_seen=candidate.created_at,
            reinforcement_count=max(1, len(candidate.source_refs)),
            contradiction_count=0,
            mutable=memory_mutability(candidate.type),
            active=True,
        )

    def _prefer_more_informative_summary(self, current: str, new_value: str) -> str:
        if len(new_value) > len(current) and not new_value.startswith(current):
            return new_value
        return current
