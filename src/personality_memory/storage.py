from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import ConversationEvent, LongTermMemory, MemoryCandidate, PersonaProfile, RevisionEntry
from .utils import detect_project_root, ensure_directory, read_json, read_jsonl, write_json, write_jsonl


@dataclass(slots=True)
class StoragePaths:
    root: Path
    data_dir: Path
    conversations: Path
    candidates: Path
    long_term: Path
    persona: Path
    revisions: Path


class Storage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = detect_project_root(root)
        data_dir = ensure_directory(self.root / "data")
        self.paths = StoragePaths(
            root=self.root,
            data_dir=data_dir,
            conversations=data_dir / "conversations.jsonl",
            candidates=data_dir / "memory_candidates.json",
            long_term=data_dir / "long_term_memory.json",
            persona=data_dir / "persona_profile.json",
            revisions=data_dir / "revisions.json",
        )
        self.ensure_storage_files()

    def ensure_storage_files(self) -> None:
        ensure_directory(self.paths.data_dir)
        if not self.paths.conversations.exists():
            self.paths.conversations.write_text("", encoding="utf-8")
        if not self.paths.candidates.exists():
            write_json(self.paths.candidates, [])
        if not self.paths.long_term.exists():
            write_json(self.paths.long_term, [])
        if not self.paths.persona.exists():
            write_json(self.paths.persona, {})
        if not self.paths.revisions.exists():
            write_json(self.paths.revisions, [])

    def load_conversation_events(self) -> list[ConversationEvent]:
        return [ConversationEvent.from_dict(item) for item in read_jsonl(self.paths.conversations)]

    def append_conversation_events(self, events: list[ConversationEvent]) -> list[ConversationEvent]:
        existing = self.load_conversation_events()
        existing_ids = {event.id for event in existing}
        added = [event for event in events if event.id not in existing_ids]
        if not added:
            return []
        serialized = [event.to_dict() for event in existing + added]
        write_jsonl(self.paths.conversations, serialized)
        return added

    def load_memory_candidates(self) -> list[MemoryCandidate]:
        payload = read_json(self.paths.candidates, [])
        return [MemoryCandidate.from_dict(item) for item in payload]

    def save_memory_candidates(self, candidates: list[MemoryCandidate]) -> None:
        write_json(self.paths.candidates, [candidate.to_dict() for candidate in candidates])

    def load_long_term_memory(self) -> list[LongTermMemory]:
        payload = read_json(self.paths.long_term, [])
        return [LongTermMemory.from_dict(item) for item in payload]

    def save_long_term_memory(self, memories: list[LongTermMemory]) -> None:
        write_json(self.paths.long_term, [memory.to_dict() for memory in memories])

    def load_persona_profile(self) -> PersonaProfile | None:
        payload = read_json(self.paths.persona, {})
        if not payload:
            return None
        return PersonaProfile.from_dict(payload)

    def save_persona_profile(self, profile: PersonaProfile | None) -> None:
        write_json(self.paths.persona, profile.to_dict() if profile is not None else {})

    def load_revisions(self) -> list[RevisionEntry]:
        payload = read_json(self.paths.revisions, [])
        return [RevisionEntry.from_dict(item) for item in payload]

    def append_revisions(self, revisions: list[RevisionEntry]) -> None:
        existing = self.load_revisions()
        existing.extend(revisions)
        write_json(self.paths.revisions, [item.to_dict() for item in existing])

    def reset(self) -> None:
        write_jsonl(self.paths.conversations, [])
        write_json(self.paths.candidates, [])
        write_json(self.paths.long_term, [])
        write_json(self.paths.persona, {})
        write_json(self.paths.revisions, [])
