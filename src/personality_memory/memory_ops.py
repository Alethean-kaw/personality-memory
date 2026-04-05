from __future__ import annotations

from .lifecycle import refresh_memory_activity
from .models import EvidenceRef, LongTermMemory, MemoryCandidate
from .utils import clamp, latest_timestamp, stable_hash


REINFORCEMENT_CONFIDENCE_BONUS = 0.04


def memory_mutability(category: str) -> bool:
    return category not in {"identity"}


def create_long_term_memory(
    candidate: MemoryCandidate,
    confidence: float,
    existing_memories: list[LongTermMemory] | None = None,
) -> LongTermMemory:
    base_id = f"ltm_{stable_hash(f'{candidate.type}|{candidate.content}')}"
    memory_id = unique_memory_id(base_id, existing_memories or [], candidate.id)
    memory = LongTermMemory(
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
        last_reinforced_at=candidate.created_at,
        lifecycle_state="active",
        staleness_score=0.0,
        stale_since=None,
        superseded_by=None,
    )
    return refresh_memory_activity(memory, reference_time=candidate.created_at)


def unique_memory_id(base_id: str, memories: list[LongTermMemory], seed: str) -> str:
    existing_ids = {memory.id for memory in memories}
    if base_id not in existing_ids:
        return base_id
    return f"{base_id}_{stable_hash(seed, length=6)}"


def merge_candidate_into_memory(memory: LongTermMemory, candidate: MemoryCandidate) -> None:
    memory.summary = prefer_more_informative_summary(memory.summary, candidate.content)
    memory.last_seen = latest_timestamp(memory.last_seen, candidate.created_at)
    memory.confidence = clamp(max(memory.confidence, candidate.confidence) + REINFORCEMENT_CONFIDENCE_BONUS, 0.0, 0.99)
    memory.reinforcement_count += 1
    memory.evidence = union_evidence(memory.evidence, candidate.source_refs)
    refresh_memory_activity(memory, reference_time=candidate.created_at)


def replace_memory_with_candidate(memory: LongTermMemory, candidate: MemoryCandidate) -> None:
    memory.summary = candidate.content
    memory.category = candidate.type
    memory.last_seen = latest_timestamp(memory.last_seen, candidate.created_at)
    memory.confidence = clamp(candidate.confidence, 0.0, 0.99)
    memory.reinforcement_count = max(1, memory.reinforcement_count + 1)
    memory.contradiction_count = 0
    memory.active = True
    memory.evidence = union_evidence(memory.evidence, candidate.source_refs)
    refresh_memory_activity(memory, reference_time=candidate.created_at)


def union_evidence(existing: list[EvidenceRef], new_refs: list[EvidenceRef]) -> list[EvidenceRef]:
    merged = list(existing)
    evidence_index = {item.conversation_event_id for item in merged}
    for ref in new_refs:
        if ref.conversation_event_id not in evidence_index:
            merged.append(ref)
            evidence_index.add(ref.conversation_event_id)
    return merged


def prefer_more_informative_summary(current: str, new_value: str) -> str:
    if len(new_value) > len(current) and not new_value.startswith(current):
        return new_value
    return current
