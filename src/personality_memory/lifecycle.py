from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import LongTermMemory
from .utils import clamp, days_between, latest_timestamp, parse_timestamp, shift_timestamp, utc_now

DEFAULT_AGING_POLICY = "default-v1"
AGELESS_CATEGORIES = {"identity"}
AGING_THRESHOLDS: dict[str, tuple[int | None, int | None]] = {
    "identity": (None, None),
    "style": (180, 360),
    "preference": (180, 360),
    "taboo": (180, 360),
    "worldview": (180, 360),
    "project": (90, 180),
    "goal": (90, 180),
    "routine": (90, 180),
    "constraint": (90, 180),
}


@dataclass(slots=True, frozen=True)
class AgingEvaluation:
    state: str
    staleness_score: float
    stale_since: str | None


def get_aging_thresholds(category: str, policy_name: str = DEFAULT_AGING_POLICY) -> tuple[int | None, int | None]:
    del policy_name
    return AGING_THRESHOLDS.get(category, (180, 360))


def lifecycle_reference(memory: LongTermMemory) -> str:
    return memory.last_reinforced_at or memory.last_seen or memory.first_seen or utc_now()


def evaluate_memory_lifecycle(
    memory: LongTermMemory,
    *,
    reference_time: str | None = None,
    aging_policy: str = DEFAULT_AGING_POLICY,
) -> AgingEvaluation:
    if memory.superseded_by:
        return AgingEvaluation(state="expired", staleness_score=1.0, stale_since=memory.stale_since or reference_time or utc_now())

    dormant_days, expired_days = get_aging_thresholds(memory.category, aging_policy)
    if dormant_days is None or expired_days is None:
        return AgingEvaluation(state="active", staleness_score=0.0, stale_since=None)

    reference = reference_time or utc_now()
    anchor = lifecycle_reference(memory)
    age_days = max(0.0, days_between(reference, anchor))

    if age_days >= expired_days:
        stale_since = shift_timestamp(anchor, days=expired_days)
        return AgingEvaluation(state="expired", staleness_score=1.0, stale_since=stale_since)

    if age_days >= dormant_days:
        stale_since = shift_timestamp(anchor, days=dormant_days)
        score = clamp(age_days / float(expired_days), 0.0, 0.99)
        return AgingEvaluation(state="dormant", staleness_score=score, stale_since=stale_since)

    score = clamp(age_days / float(max(1, dormant_days)), 0.0, 0.89)
    return AgingEvaluation(state="active", staleness_score=score, stale_since=None)


def apply_memory_lifecycle(
    memory: LongTermMemory,
    *,
    reference_time: str | None = None,
    aging_policy: str = DEFAULT_AGING_POLICY,
) -> LongTermMemory:
    if not memory.last_reinforced_at:
        memory.last_reinforced_at = lifecycle_reference(memory)

    # Preserve explicitly inactive memories from being auto-revived by lifecycle recalculation.
    if not memory.active and not memory.superseded_by:
        if memory.lifecycle_state == "active":
            memory.lifecycle_state = "expired"
            memory.staleness_score = max(memory.staleness_score, 1.0)
            memory.stale_since = memory.stale_since or reference_time or lifecycle_reference(memory)
            return memory
        if memory.lifecycle_state == "expired" and memory.stale_since is not None and memory.staleness_score >= 1.0:
            return memory

    evaluation = evaluate_memory_lifecycle(memory, reference_time=reference_time, aging_policy=aging_policy)
    memory.lifecycle_state = evaluation.state
    memory.staleness_score = evaluation.staleness_score
    memory.stale_since = evaluation.stale_since
    memory.active = memory.lifecycle_state == "active"
    return memory


def refresh_memory_activity(memory: LongTermMemory, *, reference_time: str | None = None) -> LongTermMemory:
    anchor = reference_time or latest_timestamp(memory.last_reinforced_at, memory.last_seen, memory.first_seen) or utc_now()
    memory.last_reinforced_at = anchor
    memory.last_seen = latest_timestamp(memory.last_seen, anchor)
    memory.lifecycle_state = "active"
    memory.staleness_score = 0.0
    memory.stale_since = None
    memory.active = True
    return memory


def memory_policy_description(policy_name: str = DEFAULT_AGING_POLICY) -> dict[str, Any]:
    return {
        "aging_policy": policy_name,
        "default_backend": "hybrid",
        "main_hits_include": ["active"],
        "main_hits_exclude": ["dormant", "expired"],
        "dormant_threshold_days": {
            key: value[0]
            for key, value in AGING_THRESHOLDS.items()
            if value[0] is not None
        },
        "expired_threshold_days": {
            key: value[1]
            for key, value in AGING_THRESHOLDS.items()
            if value[1] is not None
        },
    }


def latest_memory_timestamp(memories: list[LongTermMemory]) -> str | None:
    values = [lifecycle_reference(memory) for memory in memories if lifecycle_reference(memory)]
    return latest_timestamp(*values) if values else None


def sort_memories_by_freshness(memories: list[LongTermMemory]) -> list[LongTermMemory]:
    return sorted(memories, key=lambda memory: parse_timestamp(lifecycle_reference(memory)), reverse=True)

