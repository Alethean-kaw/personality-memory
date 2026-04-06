from __future__ import annotations

from dataclasses import dataclass

from .models import EvidenceRef, MemoryCandidate
from .utils import clamp, days_between, latest_timestamp, utc_now

PENDING_CANDIDATE_COOLING_DAYS = 30
PENDING_CANDIDATE_ARCHIVE_DAYS = 60
TERMINAL_CANDIDATE_ARCHIVE_DAYS = 30


@dataclass(slots=True)
class CandidateRefreshResult:
    active_candidates: list[MemoryCandidate]
    archived_candidates: list[MemoryCandidate]
    archived_count: int = 0
    restored_count: int = 0


def candidate_anchor(candidate: MemoryCandidate) -> str:
    return candidate.last_seen or candidate.created_at or utc_now()


def merge_candidate_evidence(existing: list[EvidenceRef], new_refs: list[EvidenceRef]) -> list[EvidenceRef]:
    merged = list(existing)
    seen_event_ids = {item.conversation_event_id for item in merged}
    for ref in new_refs:
        if ref.conversation_event_id not in seen_event_ids:
            merged.append(ref)
            seen_event_ids.add(ref.conversation_event_id)
    return merged


def reinforce_candidate(candidate: MemoryCandidate, *, occurred_at: str, new_refs: list[EvidenceRef] | None = None, confidence: float | None = None) -> MemoryCandidate:
    candidate.last_seen = latest_timestamp(candidate.last_seen, occurred_at)
    candidate.reinforcement_count = max(1, candidate.reinforcement_count) + 1
    if confidence is not None:
        candidate.confidence = clamp(max(candidate.confidence, confidence) + 0.02, 0.0, 0.99)
    if new_refs:
        candidate.source_refs = merge_candidate_evidence(candidate.source_refs, new_refs)
    if candidate.lifecycle_state in {"cooling", "archived"}:
        candidate.lifecycle_state = "active"
        candidate.decay_score = 0.0
        candidate.archived_at = None
        candidate.archive_reason = None
        if candidate.status == "outdated":
            candidate.status = "candidate"
    return candidate


def refresh_candidate_activity(candidate: MemoryCandidate, *, reference_time: str | None = None) -> MemoryCandidate:
    anchor = reference_time or candidate_anchor(candidate)
    candidate.last_seen = latest_timestamp(candidate.last_seen, anchor)
    candidate.lifecycle_state = "active"
    candidate.decay_score = 0.0
    candidate.archived_at = None
    candidate.archive_reason = None
    if candidate.status == "outdated":
        candidate.status = "candidate"
    return candidate


def apply_candidate_lifecycle(candidate: MemoryCandidate, *, reference_time: str | None = None) -> MemoryCandidate:
    reference = reference_time or utc_now()
    anchor = candidate_anchor(candidate)
    age_days = max(0.0, days_between(reference, anchor)) if anchor else 0.0

    if candidate.status == "review":
        candidate.lifecycle_state = "active"
        candidate.decay_score = 0.0
        return candidate

    if candidate.lifecycle_state == "archived" or candidate.archived_at is not None:
        candidate.lifecycle_state = "archived"
        candidate.decay_score = 1.0
        return candidate

    if candidate.status in {"accepted", "rejected"}:
        if age_days >= TERMINAL_CANDIDATE_ARCHIVE_DAYS:
            candidate.lifecycle_state = "archived"
            candidate.decay_score = 1.0
            candidate.archived_at = reference
            candidate.archive_reason = candidate.archive_reason or f"terminal_{candidate.status}"
        else:
            candidate.lifecycle_state = "active"
            candidate.decay_score = clamp(age_days / float(max(1, TERMINAL_CANDIDATE_ARCHIVE_DAYS)), 0.0, 0.89)
        return candidate

    if candidate.status == "outdated":
        candidate.lifecycle_state = "archived"
        candidate.decay_score = 1.0
        candidate.archived_at = candidate.archived_at or reference
        candidate.archive_reason = candidate.archive_reason or "outdated"
        return candidate

    if age_days >= PENDING_CANDIDATE_ARCHIVE_DAYS:
        candidate.status = "outdated"
        candidate.lifecycle_state = "archived"
        candidate.decay_score = 1.0
        candidate.archived_at = reference
        candidate.archive_reason = candidate.archive_reason or "stale_pending"
        return candidate

    if age_days >= PENDING_CANDIDATE_COOLING_DAYS:
        candidate.lifecycle_state = "cooling"
        candidate.decay_score = clamp(age_days / float(max(1, PENDING_CANDIDATE_ARCHIVE_DAYS)), 0.0, 0.99)
        return candidate

    candidate.lifecycle_state = "active"
    candidate.decay_score = clamp(age_days / float(max(1, PENDING_CANDIDATE_COOLING_DAYS)), 0.0, 0.89)
    return candidate


def refresh_candidate_collections(
    candidates: list[MemoryCandidate],
    archived_candidates: list[MemoryCandidate] | None = None,
    *,
    reference_time: str | None = None,
) -> CandidateRefreshResult:
    archived = list(archived_candidates or [])
    active: list[MemoryCandidate] = []
    archived_count = 0

    for candidate in candidates:
        apply_candidate_lifecycle(candidate, reference_time=reference_time)
        if candidate.lifecycle_state == "archived":
            archived.append(candidate)
            archived_count += 1
        else:
            active.append(candidate)

    deduped_archived: dict[str, MemoryCandidate] = {}
    for candidate in archived:
        deduped_archived[candidate.id] = candidate

    return CandidateRefreshResult(active_candidates=active, archived_candidates=list(deduped_archived.values()), archived_count=archived_count)


def restore_archived_candidate(
    candidate_id: str,
    *,
    candidates: list[MemoryCandidate],
    archived_candidates: list[MemoryCandidate],
    reason: str,
) -> CandidateRefreshResult:
    restored_candidate: MemoryCandidate | None = None
    remaining_archived: list[MemoryCandidate] = []
    for candidate in archived_candidates:
        if candidate.id == candidate_id and restored_candidate is None:
            restored_candidate = candidate
            continue
        remaining_archived.append(candidate)

    if restored_candidate is None:
        raise ValueError(f"Candidate {candidate_id} not found in archive.")

    restored_candidate.status = "candidate"
    restored_candidate.notes = f"Restored from archive: {reason}"
    restored_candidate.resolution_kind = None
    restored_candidate.resolved_at = None
    restored_candidate.resolved_memory_id = None
    refresh_candidate_activity(restored_candidate, reference_time=utc_now())
    candidates.append(restored_candidate)
    return CandidateRefreshResult(active_candidates=candidates, archived_candidates=remaining_archived, restored_count=1)
