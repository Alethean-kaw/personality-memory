from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EvidenceRef:
    conversation_event_id: str
    session_id: str
    message_id: str
    speaker: str
    occurred_at: str
    excerpt: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_event_id": self.conversation_event_id,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "speaker": self.speaker,
            "occurred_at": self.occurred_at,
            "excerpt": self.excerpt,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvidenceRef":
        return cls(
            conversation_event_id=payload["conversation_event_id"],
            session_id=payload["session_id"],
            message_id=payload["message_id"],
            speaker=payload["speaker"],
            occurred_at=payload["occurred_at"],
            excerpt=payload["excerpt"],
        )


@dataclass(slots=True)
class ConversationEvent:
    id: str
    session_id: str
    message_id: str
    speaker: str
    text: str
    occurred_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "speaker": self.speaker,
            "text": self.text,
            "occurred_at": self.occurred_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ConversationEvent":
        return cls(
            id=payload["id"],
            session_id=payload["session_id"],
            message_id=payload["message_id"],
            speaker=payload["speaker"],
            text=payload["text"],
            occurred_at=payload["occurred_at"],
        )


@dataclass(slots=True)
class MemoryCandidate:
    id: str
    content: str
    type: str
    confidence: float
    source_refs: list[EvidenceRef] = field(default_factory=list)
    created_at: str = ""
    status: str = "candidate"
    notes: str = ""
    resolution_kind: str | None = None
    resolved_at: str | None = None
    resolved_memory_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "type": self.type,
            "confidence": round(self.confidence, 4),
            "source_refs": [ref.to_dict() for ref in self.source_refs],
            "created_at": self.created_at,
            "status": self.status,
            "notes": self.notes,
            "resolution_kind": self.resolution_kind,
            "resolved_at": self.resolved_at,
            "resolved_memory_id": self.resolved_memory_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryCandidate":
        return cls(
            id=payload["id"],
            content=payload["content"],
            type=payload["type"],
            confidence=float(payload["confidence"]),
            source_refs=[EvidenceRef.from_dict(ref) for ref in payload.get("source_refs", [])],
            created_at=payload.get("created_at", ""),
            status=payload.get("status", "candidate"),
            notes=payload.get("notes", ""),
            resolution_kind=payload.get("resolution_kind"),
            resolved_at=payload.get("resolved_at"),
            resolved_memory_id=payload.get("resolved_memory_id"),
        )


@dataclass(slots=True)
class LongTermMemory:
    id: str
    summary: str
    category: str
    evidence: list[EvidenceRef] = field(default_factory=list)
    confidence: float = 0.0
    first_seen: str = ""
    last_seen: str = ""
    reinforcement_count: int = 0
    contradiction_count: int = 0
    mutable: bool = True
    active: bool = True
    last_reinforced_at: str = ""
    lifecycle_state: str = "active"
    staleness_score: float = 0.0
    stale_since: str | None = None
    superseded_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "summary": self.summary,
            "category": self.category,
            "evidence": [ref.to_dict() for ref in self.evidence],
            "confidence": round(self.confidence, 4),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "reinforcement_count": self.reinforcement_count,
            "contradiction_count": self.contradiction_count,
            "mutable": self.mutable,
            "active": self.active,
            "last_reinforced_at": self.last_reinforced_at,
            "lifecycle_state": self.lifecycle_state,
            "staleness_score": round(self.staleness_score, 4),
            "stale_since": self.stale_since,
            "superseded_by": self.superseded_by,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LongTermMemory":
        lifecycle_state = payload.get("lifecycle_state")
        active = bool(payload.get("active", True))
        if lifecycle_state is None:
            lifecycle_state = "active" if active else "expired"
        return cls(
            id=payload["id"],
            summary=payload["summary"],
            category=payload["category"],
            evidence=[EvidenceRef.from_dict(ref) for ref in payload.get("evidence", [])],
            confidence=float(payload["confidence"]),
            first_seen=payload.get("first_seen", ""),
            last_seen=payload.get("last_seen", ""),
            reinforcement_count=int(payload.get("reinforcement_count", 0)),
            contradiction_count=int(payload.get("contradiction_count", 0)),
            mutable=bool(payload.get("mutable", True)),
            active=active,
            last_reinforced_at=payload.get("last_reinforced_at", payload.get("last_seen", payload.get("first_seen", ""))),
            lifecycle_state=lifecycle_state,
            staleness_score=float(payload.get("staleness_score", 0.0)),
            stale_since=payload.get("stale_since"),
            superseded_by=payload.get("superseded_by"),
        )


@dataclass(slots=True)
class PersonaSignal:
    memory_id: str
    summary: str
    confidence: float
    effective_confidence: float | None = None
    contradiction_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "summary": self.summary,
            "confidence": round(self.confidence, 4),
            "effective_confidence": round(self.effective_confidence, 4) if self.effective_confidence is not None else None,
            "contradiction_count": self.contradiction_count,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PersonaSignal":
        effective_confidence = payload.get("effective_confidence")
        return cls(
            memory_id=payload["memory_id"],
            summary=payload["summary"],
            confidence=float(payload["confidence"]),
            effective_confidence=float(effective_confidence) if effective_confidence is not None else None,
            contradiction_count=int(payload.get("contradiction_count", 0)),
        )


@dataclass(slots=True)
class PersonaSection:
    summary: str
    strong_signals: list[PersonaSignal] = field(default_factory=list)
    medium_signals: list[PersonaSignal] = field(default_factory=list)
    weak_signals: list[PersonaSignal] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "strong_signals": [signal.to_dict() for signal in self.strong_signals],
            "medium_signals": [signal.to_dict() for signal in self.medium_signals],
            "weak_signals": [signal.to_dict() for signal in self.weak_signals],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PersonaSection":
        return cls(
            summary=payload["summary"],
            strong_signals=[PersonaSignal.from_dict(item) for item in payload.get("strong_signals", [])],
            medium_signals=[PersonaSignal.from_dict(item) for item in payload.get("medium_signals", [])],
            weak_signals=[PersonaSignal.from_dict(item) for item in payload.get("weak_signals", [])],
        )


@dataclass(slots=True)
class PersonaProfile:
    generated_at: str
    memory_refs: list[str]
    communication_style: PersonaSection
    priorities: PersonaSection
    recurring_interests: PersonaSection
    working_preferences: PersonaSection
    emotional_tone_preferences: PersonaSection
    likely_goals: PersonaSection
    avoidances: PersonaSection
    contested_signals: list[PersonaSignal]
    system_adaptation_notes: list[dict[str, Any]]
    markdown_summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "memory_refs": self.memory_refs,
            "communication_style": self.communication_style.to_dict(),
            "priorities": self.priorities.to_dict(),
            "recurring_interests": self.recurring_interests.to_dict(),
            "working_preferences": self.working_preferences.to_dict(),
            "emotional_tone_preferences": self.emotional_tone_preferences.to_dict(),
            "likely_goals": self.likely_goals.to_dict(),
            "avoidances": self.avoidances.to_dict(),
            "contested_signals": [signal.to_dict() for signal in self.contested_signals],
            "system_adaptation_notes": self.system_adaptation_notes,
            "markdown_summary": self.markdown_summary,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PersonaProfile":
        return cls(
            generated_at=payload["generated_at"],
            memory_refs=list(payload.get("memory_refs", [])),
            communication_style=PersonaSection.from_dict(payload["communication_style"]),
            priorities=PersonaSection.from_dict(payload["priorities"]),
            recurring_interests=PersonaSection.from_dict(payload["recurring_interests"]),
            working_preferences=PersonaSection.from_dict(payload["working_preferences"]),
            emotional_tone_preferences=PersonaSection.from_dict(payload["emotional_tone_preferences"]),
            likely_goals=PersonaSection.from_dict(payload["likely_goals"]),
            avoidances=PersonaSection.from_dict(payload["avoidances"]),
            contested_signals=[PersonaSignal.from_dict(item) for item in payload.get("contested_signals", [])],
            system_adaptation_notes=list(payload.get("system_adaptation_notes", [])),
            markdown_summary=payload.get("markdown_summary", ""),
        )


@dataclass(slots=True)
class ReviewItem:
    id: str
    candidate_id: str
    target_memory_id: str | None
    kind: str
    reason: str
    opened_at: str
    status: str = "open"
    resolution_action: str | None = None
    resolution_notes: str | None = None
    resolved_at: str | None = None
    revision_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "target_memory_id": self.target_memory_id,
            "kind": self.kind,
            "reason": self.reason,
            "opened_at": self.opened_at,
            "status": self.status,
            "resolution_action": self.resolution_action,
            "resolution_notes": self.resolution_notes,
            "resolved_at": self.resolved_at,
            "revision_ids": list(self.revision_ids),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReviewItem":
        return cls(
            id=payload["id"],
            candidate_id=payload["candidate_id"],
            target_memory_id=payload.get("target_memory_id"),
            kind=payload["kind"],
            reason=payload.get("reason", ""),
            opened_at=payload["opened_at"],
            status=payload.get("status", "open"),
            resolution_action=payload.get("resolution_action"),
            resolution_notes=payload.get("resolution_notes"),
            resolved_at=payload.get("resolved_at"),
            revision_ids=list(payload.get("revision_ids", [])),
        )


@dataclass(slots=True)
class RetrievalHit:
    memory_id: str
    summary: str
    category: str
    confidence: float
    effective_confidence: float
    relevance_score: float
    supporting_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "summary": self.summary,
            "category": self.category,
            "confidence": round(self.confidence, 4),
            "effective_confidence": round(self.effective_confidence, 4),
            "relevance_score": round(self.relevance_score, 4),
            "supporting_evidence": list(self.supporting_evidence),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RetrievalHit":
        return cls(
            memory_id=payload["memory_id"],
            summary=payload["summary"],
            category=payload["category"],
            confidence=float(payload["confidence"]),
            effective_confidence=float(payload["effective_confidence"]),
            relevance_score=float(payload["relevance_score"]),
            supporting_evidence=list(payload.get("supporting_evidence", [])),
        )


@dataclass(slots=True)
class RetrievalResult:
    query: str
    generated_at: str
    memory_hits: list[RetrievalHit]
    persona_adaptation_notes: list[dict[str, Any]]
    contested_signals: list[PersonaSignal] = field(default_factory=list)
    open_reviews: list[ReviewItem] = field(default_factory=list)
    usage_guidance: list[str] = field(default_factory=list)
    memory_policy: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1
    profile_id: str = "default"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "query": self.query,
            "generated_at": self.generated_at,
            "memory_hits": [hit.to_dict() for hit in self.memory_hits],
            "persona_adaptation_notes": list(self.persona_adaptation_notes),
            "contested_signals": [signal.to_dict() for signal in self.contested_signals],
            "open_reviews": [item.to_dict() for item in self.open_reviews],
            "usage_guidance": list(self.usage_guidance),
            "memory_policy": dict(self.memory_policy),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RetrievalResult":
        return cls(
            schema_version=int(payload.get("schema_version", 1)),
            profile_id=payload.get("profile_id", "default"),
            query=payload["query"],
            generated_at=payload["generated_at"],
            memory_hits=[RetrievalHit.from_dict(item) for item in payload.get("memory_hits", [])],
            persona_adaptation_notes=list(payload.get("persona_adaptation_notes", [])),
            contested_signals=[PersonaSignal.from_dict(item) for item in payload.get("contested_signals", [])],
            open_reviews=[ReviewItem.from_dict(item) for item in payload.get("open_reviews", [])],
            usage_guidance=list(payload.get("usage_guidance", [])),
            memory_policy=dict(payload.get("memory_policy", {})),
        )


@dataclass(slots=True)
class RevisionEntry:
    id: str
    entity_type: str
    entity_id: str
    action: str
    timestamp: str
    reason: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "action": self.action,
            "timestamp": self.timestamp,
            "reason": self.reason,
            "before": self.before,
            "after": self.after,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RevisionEntry":
        return cls(
            id=payload["id"],
            entity_type=payload["entity_type"],
            entity_id=payload["entity_id"],
            action=payload["action"],
            timestamp=payload["timestamp"],
            reason=payload.get("reason", ""),
            before=payload.get("before"),
            after=payload.get("after"),
        )


@dataclass(slots=True)
class ProfileMetadata:
    id: str
    display_name: str
    created_at: str
    updated_at: str
    backend: str
    aging_policy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "backend": self.backend,
            "aging_policy": self.aging_policy,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProfileMetadata":
        return cls(
            id=payload["id"],
            display_name=payload.get("display_name", payload["id"]),
            created_at=payload.get("created_at", ""),
            updated_at=payload.get("updated_at", payload.get("created_at", "")),
            backend=payload.get("backend", "hybrid"),
            aging_policy=payload.get("aging_policy", "default-v1"),
        )


@dataclass(slots=True)
class ProfileRegistry:
    schema_version: int
    default_profile_id: str
    profiles: list[ProfileMetadata] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "default_profile_id": self.default_profile_id,
            "profiles": [profile.to_dict() for profile in self.profiles],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProfileRegistry":
        return cls(
            schema_version=int(payload.get("schema_version", 1)),
            default_profile_id=payload.get("default_profile_id", "default"),
            profiles=[ProfileMetadata.from_dict(item) for item in payload.get("profiles", [])],
        )


@dataclass(slots=True)
class MigrationRecord:
    id: str
    name: str
    applied_at: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "applied_at": self.applied_at,
            "status": self.status,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MigrationRecord":
        return cls(
            id=payload["id"],
            name=payload["name"],
            applied_at=payload["applied_at"],
            status=payload.get("status", "applied"),
            details=dict(payload.get("details", {})),
        )
