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
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LongTermMemory":
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
            active=bool(payload.get("active", True)),
        )


@dataclass(slots=True)
class PersonaSignal:
    memory_id: str
    summary: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "summary": self.summary,
            "confidence": round(self.confidence, 4),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PersonaSignal":
        return cls(
            memory_id=payload["memory_id"],
            summary=payload["summary"],
            confidence=float(payload["confidence"]),
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
            system_adaptation_notes=list(payload.get("system_adaptation_notes", [])),
            markdown_summary=payload.get("markdown_summary", ""),
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
