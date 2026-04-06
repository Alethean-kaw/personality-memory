from __future__ import annotations

from dataclasses import dataclass, field

from .candidate_lifecycle import refresh_candidate_activity, restore_archived_candidate
from .lifecycle import refresh_memory_activity
from .memory_ops import create_long_term_memory, merge_candidate_into_memory, replace_memory_with_candidate
from .models import LongTermMemory, MemoryCandidate, ReviewItem, RevisionEntry
from .utils import stable_hash, utc_now


@dataclass(slots=True)
class GovernanceResult:
    candidates: list[MemoryCandidate]
    archived_candidates: list[MemoryCandidate]
    memories: list[LongTermMemory]
    review_items: list[ReviewItem]
    revisions: list[RevisionEntry] = field(default_factory=list)


class MemoryGovernanceManager:
    def resolve_review(self, *, review_id: str, action: str, reason: str, candidates: list[MemoryCandidate], memories: list[LongTermMemory], review_items: list[ReviewItem], memory_id: str | None = None, archived_candidates: list[MemoryCandidate] | None = None) -> GovernanceResult:
        review = self._find_review(review_items, review_id)
        if review is None:
            raise ValueError(f"Review item {review_id} not found.")
        if review.status != "open":
            raise ValueError(f"Review item {review_id} is not open.")
        candidate = self._find_candidate(candidates, review.candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {review.candidate_id} referenced by review {review_id} was not found.")
        revisions: list[RevisionEntry] = []
        candidate_before = self._candidate_snapshot(candidate, "active")
        review_before = review.to_dict()
        resolved_memory_id = review.target_memory_id
        archived = list(archived_candidates or [])

        if action == "accept-candidate":
            memory = create_long_term_memory(candidate, candidate.confidence, memories)
            memories.append(memory)
            resolved_memory_id = memory.id
            revisions.append(self._revision("long_term_memory", memory.id, "create", reason, None, memory.to_dict()))
            candidate.status = "accepted"
            candidate.notes = f"Accepted by review {review.id}: {reason}"
            candidate.resolution_kind = "accepted_by_review"
            candidate.resolved_at = utc_now()
            candidate.resolved_memory_id = memory.id
        elif action == "merge-into":
            if not memory_id:
                raise ValueError("--memory-id is required for merge-into.")
            target = self._find_memory(memories, memory_id)
            if target is None:
                raise ValueError(f"Memory {memory_id} not found.")
            if not target.mutable:
                raise ValueError(f"Memory {memory_id} is immutable and cannot be merged into automatically.")
            memory_before = target.to_dict()
            merge_candidate_into_memory(target, candidate)
            refresh_memory_activity(target, reference_time=candidate.created_at)
            resolved_memory_id = target.id
            revisions.append(self._revision("long_term_memory", target.id, "merge_by_review", reason, memory_before, target.to_dict()))
            candidate.status = "accepted"
            candidate.notes = f"Merged by review {review.id} into {target.id}: {reason}"
            candidate.resolution_kind = "merged_by_review"
            candidate.resolved_at = utc_now()
            candidate.resolved_memory_id = target.id
            review.target_memory_id = target.id
        elif action == "replace-memory":
            if not memory_id:
                raise ValueError("--memory-id is required for replace-memory.")
            target = self._find_memory(memories, memory_id)
            if target is None:
                raise ValueError(f"Memory {memory_id} not found.")
            memory_before = target.to_dict()
            replace_memory_with_candidate(target, candidate)
            refresh_memory_activity(target, reference_time=candidate.created_at)
            resolved_memory_id = target.id
            revisions.append(self._revision("long_term_memory", target.id, "replace_by_review", reason, memory_before, target.to_dict()))
            candidate.status = "accepted"
            candidate.notes = f"Replaced memory {target.id} by review {review.id}: {reason}"
            candidate.resolution_kind = "replaced_by_review"
            candidate.resolved_at = utc_now()
            candidate.resolved_memory_id = target.id
            review.target_memory_id = target.id
        elif action == "reject-candidate":
            candidate.status = "rejected"
            candidate.notes = f"Rejected by review {review.id}: {reason}"
            candidate.resolution_kind = "rejected_by_review"
            candidate.resolved_at = utc_now()
            candidate.resolved_memory_id = review.target_memory_id
        else:
            raise ValueError(f"Unsupported review resolution action: {action}")

        revisions.append(self._revision("memory_candidate", candidate.id, action, reason, candidate_before, self._candidate_snapshot(candidate, "active")))
        review.status = "resolved"
        review.resolution_action = action
        review.resolution_notes = reason
        review.resolved_at = utc_now()
        review.target_memory_id = resolved_memory_id
        review_revision = self._revision("review_item", review.id, "resolve", reason, review_before, review.to_dict())
        revisions.append(review_revision)
        review.revision_ids.extend([revision.id for revision in revisions])
        return GovernanceResult(candidates=candidates, archived_candidates=archived, memories=memories, review_items=review_items, revisions=revisions)

    def reopen_candidate(self, *, candidate_id: str, reason: str, candidates: list[MemoryCandidate], review_items: list[ReviewItem], memories: list[LongTermMemory], archived_candidates: list[MemoryCandidate] | None = None) -> GovernanceResult:
        archived = list(archived_candidates or [])
        candidate = self._find_candidate(candidates, candidate_id)
        source = "active"
        if candidate is None:
            refresh = restore_archived_candidate(candidate_id, candidates=candidates, archived_candidates=archived, reason=reason)
            candidates = refresh.active_candidates
            archived = refresh.archived_candidates
            candidate = self._find_candidate(candidates, candidate_id)
            source = "archive"
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found.")

        revisions: list[RevisionEntry] = []
        candidate_before = self._candidate_snapshot(candidate, source)
        candidate.status = "candidate"
        candidate.notes = f"Reopened manually: {reason}"
        candidate.resolution_kind = None
        candidate.resolved_at = None
        candidate.resolved_memory_id = None
        refresh_candidate_activity(candidate, reference_time=utc_now())
        revisions.append(self._revision("memory_candidate", candidate.id, "reopen", reason, candidate_before, self._candidate_snapshot(candidate, "active")))

        for review in review_items:
            if review.candidate_id != candidate_id or review.status != "open":
                continue
            review_before = review.to_dict()
            review.status = "dismissed"
            review.resolution_action = "reopen-candidate"
            review.resolution_notes = reason
            review.resolved_at = utc_now()
            review_revision = self._revision("review_item", review.id, "dismiss", reason, review_before, review.to_dict())
            revisions.append(review_revision)
            review.revision_ids.append(review_revision.id)

        return GovernanceResult(candidates=candidates, archived_candidates=archived, memories=memories, review_items=review_items, revisions=revisions)

    def _candidate_snapshot(self, candidate: MemoryCandidate, store: str) -> dict[str, object]:
        payload = candidate.to_dict()
        payload["candidate_store"] = store
        return payload

    def _find_candidate(self, candidates: list[MemoryCandidate], candidate_id: str) -> MemoryCandidate | None:
        for candidate in candidates:
            if candidate.id == candidate_id:
                return candidate
        return None

    def _find_memory(self, memories: list[LongTermMemory], memory_id: str) -> LongTermMemory | None:
        for memory in memories:
            if memory.id == memory_id:
                return memory
        return None

    def _find_review(self, review_items: list[ReviewItem], review_id: str) -> ReviewItem | None:
        for item in review_items:
            if item.id == review_id:
                return item
        return None

    def _revision(self, entity_type: str, entity_id: str, action: str, reason: str, before: dict[str, object] | None, after: dict[str, object] | None) -> RevisionEntry:
        timestamp = utc_now()
        return RevisionEntry(id=f"rev_{stable_hash(f'{entity_type}|{entity_id}|{action}|{timestamp}')}", entity_type=entity_type, entity_id=entity_id, action=action, timestamp=timestamp, reason=reason, before=before, after=after)
