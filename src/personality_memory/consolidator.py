from __future__ import annotations

from dataclasses import dataclass, field

from .backends import SimilarityBackend, get_backend
from .lifecycle import DEFAULT_AGING_POLICY, apply_memory_lifecycle, refresh_memory_activity
from .memory_ops import create_long_term_memory, merge_candidate_into_memory
from .models import LongTermMemory, MemoryCandidate, ReviewItem, RevisionEntry
from .scoring import contradiction_score
from .utils import clamp, latest_timestamp, sort_timestamp, stable_hash, utc_now


@dataclass(slots=True)
class ConsolidationResult:
    candidates: list[MemoryCandidate]
    memories: list[LongTermMemory]
    review_items: list[ReviewItem]
    revisions: list[RevisionEntry] = field(default_factory=list)
    created: int = 0
    updated: int = 0
    conflicts: int = 0
    pending: int = 0
    candidates_archived: int = 0
    candidates_restored: int = 0


class MemoryConsolidator:
    def __init__(self, similarity_threshold: float = 0.76, promotion_threshold: float = 0.72, contradiction_threshold: float = 0.35, backend_name: str = "hybrid", backend: SimilarityBackend | None = None, aging_policy: str = DEFAULT_AGING_POLICY) -> None:
        self.similarity_threshold = similarity_threshold
        self.promotion_threshold = promotion_threshold
        self.contradiction_threshold = contradiction_threshold
        self.backend = backend or get_backend(backend_name)
        self.aging_policy = aging_policy

    def consolidate(self, candidates: list[MemoryCandidate], memories: list[LongTermMemory], review_items: list[ReviewItem] | None = None, *, reference_time: str | None = None) -> ConsolidationResult:
        reference = reference_time or self._default_reference_time(candidates, memories)
        for memory in memories:
            apply_memory_lifecycle(memory, reference_time=reference, aging_policy=self.aging_policy)

        reviews = list(review_items or [])
        revisions: list[RevisionEntry] = []
        created = updated = conflicts = pending = 0
        support = self._compute_candidate_support(candidates)

        for candidate in sorted(candidates, key=lambda item: (sort_timestamp(item.created_at), -item.confidence, item.id)):
            if candidate.status != "candidate" or candidate.lifecycle_state != "active":
                continue

            active_memories = [memory for memory in memories if memory.active and memory.lifecycle_state == "active"]
            inactive_memories = [memory for memory in memories if not (memory.active and memory.lifecycle_state == "active")]
            best_match, best_similarity = self._best_match(candidate, active_memories)
            if best_match is not None:
                contradiction = contradiction_score(best_match.summary, candidate.content)
                if contradiction >= self.contradiction_threshold:
                    if best_match.mutable:
                        best_match.contradiction_count += 1
                        best_match.last_seen = latest_timestamp(best_match.last_seen, candidate.created_at)
                    self._resolve_candidate(candidate, status="review", notes=f"Potential contradiction with {best_match.id}", resolution_kind="conflict", resolved_memory_id=best_match.id)
                    self._open_review_item(reviews, candidate, best_match.id, kind="conflict", reason=f"Candidate {candidate.id} may contradict memory {best_match.id}.")
                    conflicts += 1
                    if best_match.mutable:
                        revisions.append(RevisionEntry(id=f"rev_{stable_hash(f'conflict|{best_match.id}|{candidate.id}|{utc_now()}')}", entity_type="long_term_memory", entity_id=best_match.id, action="conflict", timestamp=utc_now(), reason=f"Candidate {candidate.id} conflicts with memory {best_match.id}", before=None, after=best_match.to_dict()))
                    continue
                if best_similarity >= self.similarity_threshold:
                    if not best_match.mutable:
                        self._resolve_candidate(candidate, status="accepted", notes=f"Matched immutable memory {best_match.id}; no auto-merge", resolution_kind="matched_immutable", resolved_memory_id=best_match.id)
                        continue
                    before = best_match.to_dict()
                    merge_candidate_into_memory(best_match, candidate)
                    refresh_memory_activity(best_match, reference_time=candidate.created_at)
                    self._resolve_candidate(candidate, status="accepted", notes=f"Merged into {best_match.id}", resolution_kind="merged", resolved_memory_id=best_match.id)
                    updated += 1
                    revisions.append(RevisionEntry(id=f"rev_{stable_hash(f'reinforce|{best_match.id}|{candidate.id}|{utc_now()}')}", entity_type="long_term_memory", entity_id=best_match.id, action="reinforce", timestamp=utc_now(), reason=f"Candidate {candidate.id} reinforced memory {best_match.id}", before=before, after=best_match.to_dict()))
                    continue

            inactive_match, inactive_similarity = self._best_match(candidate, inactive_memories)
            if inactive_match is not None and inactive_similarity >= self.similarity_threshold:
                if not inactive_match.mutable:
                    self._resolve_candidate(candidate, status="accepted", notes=f"Matched immutable inactive memory {inactive_match.id}; no auto-merge", resolution_kind="matched_immutable", resolved_memory_id=inactive_match.id)
                    continue
                before = inactive_match.to_dict()
                merge_candidate_into_memory(inactive_match, candidate)
                refresh_memory_activity(inactive_match, reference_time=candidate.created_at)
                self._resolve_candidate(candidate, status="accepted", notes=f"Revived and merged into {inactive_match.id}", resolution_kind="merged", resolved_memory_id=inactive_match.id)
                updated += 1
                revisions.append(RevisionEntry(id=f"rev_{stable_hash(f'revive|{inactive_match.id}|{candidate.id}|{utc_now()}')}", entity_type="long_term_memory", entity_id=inactive_match.id, action="revive", timestamp=utc_now(), reason=f"Candidate {candidate.id} revived memory {inactive_match.id}", before=before, after=inactive_match.to_dict()))
                continue

            support_count = support.get(candidate.id, 1)
            effective_confidence = clamp(candidate.confidence + max(0, support_count - 1) * 0.07, 0.0, 0.98)
            if effective_confidence >= self.promotion_threshold:
                memory = create_long_term_memory(candidate, effective_confidence, memories)
                memories.append(memory)
                self._resolve_candidate(candidate, status="accepted", notes=f"Promoted to {memory.id}", resolution_kind="promoted", resolved_memory_id=memory.id)
                created += 1
                revisions.append(RevisionEntry(id=f"rev_{stable_hash(f'create|{memory.id}|{candidate.id}|{utc_now()}')}", entity_type="long_term_memory", entity_id=memory.id, action="create", timestamp=utc_now(), reason=f"Candidate {candidate.id} promoted into long-term memory", before=None, after=memory.to_dict()))
            else:
                self._mark_candidate_pending(candidate, notes=f"Needs more evidence (support={support_count})")
                pending += 1

        for memory in memories:
            apply_memory_lifecycle(memory, reference_time=reference, aging_policy=self.aging_policy)
        return ConsolidationResult(candidates=candidates, memories=memories, review_items=reviews, revisions=revisions, created=created, updated=updated, conflicts=conflicts, pending=pending)

    def _default_reference_time(self, candidates: list[MemoryCandidate], memories: list[LongTermMemory]) -> str:
        timestamps = [candidate.created_at for candidate in candidates if candidate.created_at]
        timestamps.extend(memory.last_reinforced_at or memory.last_seen or memory.first_seen for memory in memories if (memory.last_reinforced_at or memory.last_seen or memory.first_seen))
        return latest_timestamp(*timestamps) or utc_now()

    def _compute_candidate_support(self, candidates: list[MemoryCandidate]) -> dict[str, int]:
        pending = [candidate for candidate in candidates if candidate.status == "candidate" and candidate.lifecycle_state == "active"]
        support = {candidate.id: 1 for candidate in pending}
        for index, candidate in enumerate(pending):
            for other in pending[index + 1 :]:
                if candidate.type != other.type:
                    continue
                if clamp(self.backend.similarity(candidate.content, other.content) + 0.03, 0.0, 0.99) >= self.similarity_threshold:
                    support[candidate.id] += 1
                    support[other.id] += 1
        return support

    def _best_match(self, candidate: MemoryCandidate, memories: list[LongTermMemory]) -> tuple[LongTermMemory | None, float]:
        best_memory: LongTermMemory | None = None
        best_similarity = 0.0
        for memory in memories:
            if memory.category != candidate.type:
                continue
            score = clamp(self.backend.similarity(memory.summary, candidate.content) + 0.03, 0.0, 0.99)
            if score > best_similarity:
                best_similarity = score
                best_memory = memory
        return best_memory, best_similarity

    def _open_review_item(self, review_items: list[ReviewItem], candidate: MemoryCandidate, target_memory_id: str | None, *, kind: str, reason: str) -> ReviewItem:
        for item in review_items:
            if item.status == "open" and item.candidate_id == candidate.id and item.target_memory_id == target_memory_id and item.kind == kind:
                item.reason = reason
                return item
        review_item = ReviewItem(id=f"review_{stable_hash(f'{candidate.id}|{target_memory_id}|{kind}|{utc_now()}')}", candidate_id=candidate.id, target_memory_id=target_memory_id, kind=kind, reason=reason, opened_at=utc_now())
        review_items.append(review_item)
        return review_item

    def _mark_candidate_pending(self, candidate: MemoryCandidate, notes: str) -> None:
        candidate.status = "candidate"
        candidate.notes = notes
        candidate.resolution_kind = None
        candidate.resolved_at = None
        candidate.resolved_memory_id = None

    def _resolve_candidate(self, candidate: MemoryCandidate, *, status: str, notes: str, resolution_kind: str, resolved_memory_id: str | None) -> None:
        candidate.status = status
        candidate.notes = notes
        candidate.resolution_kind = resolution_kind
        candidate.resolved_at = utc_now()
        candidate.resolved_memory_id = resolved_memory_id
