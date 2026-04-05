from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .lifecycle import DEFAULT_AGING_POLICY
from .models import (
    ConversationEvent,
    LongTermMemory,
    MemoryCandidate,
    MigrationRecord,
    PersonaProfile,
    ProfileMetadata,
    ProfileRegistry,
    ReviewItem,
    RevisionEntry,
)
from .utils import (
    copy_if_exists,
    detect_project_root,
    ensure_directory,
    read_json,
    read_jsonl,
    slugify_text,
    stable_hash,
    utc_now,
    write_json,
    write_jsonl,
)

SCHEMA_VERSION = 2
DEFAULT_PROFILE_ID = "default"
DEFAULT_BACKEND = "hybrid"

FLAT_DATA_FILES = {
    "conversations": "conversations.jsonl",
    "candidates": "memory_candidates.json",
    "long_term": "long_term_memory.json",
    "persona": "persona_profile.json",
    "revisions": "revisions.json",
    "review_items": "review_items.json",
}


@dataclass(slots=True)
class StoragePaths:
    root: Path
    data_dir: Path
    registry: Path
    migrations: Path
    profiles_dir: Path
    legacy_backup_dir: Path
    profile_dir: Path
    conversations: Path
    candidates: Path
    long_term: Path
    persona: Path
    revisions: Path
    review_items: Path


class Storage:
    def __init__(self, root: Path | None = None, profile_id: str | None = None) -> None:
        self.root = detect_project_root(root)
        self.data_dir = ensure_directory(self.root / "data")
        self.registry_path = self.data_dir / "registry.json"
        self.migrations_path = self.data_dir / "migrations.json"
        self.profiles_dir = ensure_directory(self.data_dir / "profiles")
        self.legacy_backup_dir = ensure_directory(self.data_dir / "legacy_backup")
        self._last_migration: MigrationRecord | None = None

        self._ensure_layout()
        self.registry = self.load_registry()
        self.profile_id = profile_id or self.registry.default_profile_id
        if self.get_profile_metadata(self.profile_id) is None:
            raise ValueError(f"Profile {self.profile_id} does not exist.")
        self.paths = self._build_paths(self.profile_id)
        self.ensure_storage_files()

    def _build_paths(self, profile_id: str) -> StoragePaths:
        profile_dir = ensure_directory(self.profiles_dir / profile_id)
        return StoragePaths(
            root=self.root,
            data_dir=self.data_dir,
            registry=self.registry_path,
            migrations=self.migrations_path,
            profiles_dir=self.profiles_dir,
            legacy_backup_dir=self.legacy_backup_dir,
            profile_dir=profile_dir,
            conversations=profile_dir / FLAT_DATA_FILES["conversations"],
            candidates=profile_dir / FLAT_DATA_FILES["candidates"],
            long_term=profile_dir / FLAT_DATA_FILES["long_term"],
            persona=profile_dir / FLAT_DATA_FILES["persona"],
            revisions=profile_dir / FLAT_DATA_FILES["revisions"],
            review_items=profile_dir / FLAT_DATA_FILES["review_items"],
        )

    def _flat_legacy_files(self) -> dict[str, Path]:
        return {
            key: self.data_dir / filename
            for key, filename in FLAT_DATA_FILES.items()
            if (self.data_dir / filename).exists()
        }

    def _ensure_layout(self) -> None:
        if self.registry_path.exists():
            if not self.migrations_path.exists():
                write_json(self.migrations_path, [])
            return

        legacy_files = self._flat_legacy_files()
        if legacy_files:
            self._migrate_flat_storage(legacy_files)
            return

        registry = ProfileRegistry(
            schema_version=SCHEMA_VERSION,
            default_profile_id=DEFAULT_PROFILE_ID,
            profiles=[self._make_profile_metadata(DEFAULT_PROFILE_ID, "Default")],
        )
        write_json(self.registry_path, registry.to_dict())
        write_json(self.migrations_path, [])
        default_paths = self._build_paths(DEFAULT_PROFILE_ID)
        self._ensure_profile_files(default_paths)

    def _make_profile_metadata(self, profile_id: str, display_name: str) -> ProfileMetadata:
        timestamp = utc_now()
        return ProfileMetadata(
            id=profile_id,
            display_name=display_name,
            created_at=timestamp,
            updated_at=timestamp,
            backend=DEFAULT_BACKEND,
            aging_policy=DEFAULT_AGING_POLICY,
        )

    def _migrate_flat_storage(self, legacy_files: dict[str, Path]) -> None:
        backup_dir = ensure_directory(self.legacy_backup_dir / "v1-flat")
        default_profile_dir = ensure_directory(self.profiles_dir / DEFAULT_PROFILE_ID)
        migrated_files: list[str] = []

        for key, source in legacy_files.items():
            migrated_files.append(source.name)
            backup_path = backup_dir / source.name
            profile_path = default_profile_dir / source.name
            if not backup_path.exists():
                copy_if_exists(source, backup_path)
            copy_if_exists(source, profile_path)
            try:
                source.unlink()
            except OSError:
                pass

        registry = ProfileRegistry(
            schema_version=SCHEMA_VERSION,
            default_profile_id=DEFAULT_PROFILE_ID,
            profiles=[self._make_profile_metadata(DEFAULT_PROFILE_ID, "Default")],
        )
        write_json(self.registry_path, registry.to_dict())
        migration = MigrationRecord(
            id=f"migration_{stable_hash(f'flat-to-profile|{utc_now()}')}",
            name="flat-data-to-profiles",
            applied_at=utc_now(),
            status="applied",
            details={
                "source": "v1-flat",
                "profile_id": DEFAULT_PROFILE_ID,
                "files": migrated_files,
                "backup_dir": str(backup_dir),
            },
        )
        write_json(self.migrations_path, [migration.to_dict()])
        self._last_migration = migration
        self._ensure_profile_files(self._build_paths(DEFAULT_PROFILE_ID))

    def ensure_storage_files(self) -> None:
        self._ensure_profile_files(self.paths)

    def _ensure_profile_files(self, paths: StoragePaths) -> None:
        ensure_directory(paths.profile_dir)
        if not paths.conversations.exists():
            paths.conversations.write_text("", encoding="utf-8")
        if not paths.candidates.exists():
            write_json(paths.candidates, [])
        if not paths.long_term.exists():
            write_json(paths.long_term, [])
        if not paths.persona.exists():
            write_json(paths.persona, {})
        if not paths.revisions.exists():
            write_json(paths.revisions, [])
        if not paths.review_items.exists():
            write_json(paths.review_items, [])

    def load_registry(self) -> ProfileRegistry:
        payload = read_json(self.registry_path, {})
        if not payload:
            return ProfileRegistry(schema_version=SCHEMA_VERSION, default_profile_id=DEFAULT_PROFILE_ID, profiles=[])
        return ProfileRegistry.from_dict(payload)

    def save_registry(self, registry: ProfileRegistry) -> None:
        registry.schema_version = SCHEMA_VERSION
        write_json(self.registry_path, registry.to_dict())
        self.registry = registry

    def load_migrations(self) -> list[MigrationRecord]:
        payload = read_json(self.migrations_path, [])
        return [MigrationRecord.from_dict(item) for item in payload]

    def save_migrations(self, migrations: list[MigrationRecord]) -> None:
        write_json(self.migrations_path, [item.to_dict() for item in migrations])

    def append_migration(self, migration: MigrationRecord) -> None:
        migrations = self.load_migrations()
        if any(item.id == migration.id for item in migrations):
            return
        migrations.append(migration)
        self.save_migrations(migrations)
        self._last_migration = migration

    def migration_status(self) -> dict[str, object]:
        return {
            "schema_version": self.registry.schema_version,
            "default_profile_id": self.registry.default_profile_id,
            "profiles": [item.id for item in self.registry.profiles],
            "last_migration": self._last_migration.to_dict() if self._last_migration is not None else None,
        }

    def list_profiles(self) -> list[ProfileMetadata]:
        return sorted(self.registry.profiles, key=lambda item: item.id)

    def get_profile_metadata(self, profile_id: str | None = None) -> ProfileMetadata | None:
        target = profile_id or getattr(self, "profile_id", None) or DEFAULT_PROFILE_ID
        for profile in self.registry.profiles:
            if profile.id == target:
                return profile
        return None

    def create_profile(
        self,
        profile_id: str,
        *,
        display_name: str | None = None,
        backend: str = DEFAULT_BACKEND,
        aging_policy: str = DEFAULT_AGING_POLICY,
    ) -> ProfileMetadata:
        normalized_id = slugify_text(profile_id, default=DEFAULT_PROFILE_ID)
        if self.get_profile_metadata(normalized_id) is not None:
            raise ValueError(f"Profile {normalized_id} already exists.")
        timestamp = utc_now()
        metadata = ProfileMetadata(
            id=normalized_id,
            display_name=display_name or profile_id,
            created_at=timestamp,
            updated_at=timestamp,
            backend=backend,
            aging_policy=aging_policy,
        )
        self.registry.profiles.append(metadata)
        self.save_registry(self.registry)
        self._ensure_profile_files(self._build_paths(normalized_id))
        return metadata

    def set_default_profile(self, profile_id: str) -> ProfileMetadata:
        profile = self.get_profile_metadata(profile_id)
        if profile is None:
            raise ValueError(f"Profile {profile_id} does not exist.")
        self.registry.default_profile_id = profile_id
        profile.updated_at = utc_now()
        self.save_registry(self.registry)
        return profile

    def touch_profile(self, profile_id: str | None = None, *, backend: str | None = None, aging_policy: str | None = None) -> None:
        profile = self.get_profile_metadata(profile_id)
        if profile is None:
            return
        if backend is not None:
            profile.backend = backend
        if aging_policy is not None:
            profile.aging_policy = aging_policy
        profile.updated_at = utc_now()
        self.save_registry(self.registry)

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
        self.touch_profile(self.profile_id)
        return added

    def load_memory_candidates(self) -> list[MemoryCandidate]:
        payload = read_json(self.paths.candidates, [])
        return [MemoryCandidate.from_dict(item) for item in payload]

    def save_memory_candidates(self, candidates: list[MemoryCandidate]) -> None:
        write_json(self.paths.candidates, [candidate.to_dict() for candidate in candidates])
        self.touch_profile(self.profile_id)

    def load_long_term_memory(self) -> list[LongTermMemory]:
        payload = read_json(self.paths.long_term, [])
        return [LongTermMemory.from_dict(item) for item in payload]

    def save_long_term_memory(self, memories: list[LongTermMemory]) -> None:
        write_json(self.paths.long_term, [memory.to_dict() for memory in memories])
        self.touch_profile(self.profile_id)

    def load_persona_profile(self) -> PersonaProfile | None:
        payload = read_json(self.paths.persona, {})
        if not payload:
            return None
        return PersonaProfile.from_dict(payload)

    def save_persona_profile(self, profile: PersonaProfile | None) -> None:
        write_json(self.paths.persona, profile.to_dict() if profile is not None else {})
        self.touch_profile(self.profile_id)

    def load_revisions(self) -> list[RevisionEntry]:
        payload = read_json(self.paths.revisions, [])
        return [RevisionEntry.from_dict(item) for item in payload]

    def append_revisions(self, revisions: list[RevisionEntry]) -> None:
        existing = self.load_revisions()
        existing.extend(revisions)
        write_json(self.paths.revisions, [item.to_dict() for item in existing])
        self.touch_profile(self.profile_id)

    def load_review_items(self) -> list[ReviewItem]:
        payload = read_json(self.paths.review_items, [])
        return [ReviewItem.from_dict(item) for item in payload]

    def save_review_items(self, review_items: list[ReviewItem]) -> None:
        write_json(self.paths.review_items, [item.to_dict() for item in review_items])
        self.touch_profile(self.profile_id)

    def export_all_profiles_state(self) -> dict[str, dict[str, object]]:
        snapshots: dict[str, dict[str, object]] = {}
        for profile in self.list_profiles():
            scoped = Storage(self.root, profile.id)
            persona = scoped.load_persona_profile()
            snapshots[profile.id] = {
                "metadata": profile.to_dict(),
                "conversation_events": [event.to_dict() for event in scoped.load_conversation_events()],
                "memory_candidates": [candidate.to_dict() for candidate in scoped.load_memory_candidates()],
                "long_term_memory": [memory.to_dict() for memory in scoped.load_long_term_memory()],
                "persona_profile": persona.to_dict() if persona else {},
                "review_items": [item.to_dict() for item in scoped.load_review_items()],
                "revisions": [entry.to_dict() for entry in scoped.load_revisions()],
            }
        return snapshots

    def reset(self) -> None:
        write_jsonl(self.paths.conversations, [])
        write_json(self.paths.candidates, [])
        write_json(self.paths.long_term, [])
        write_json(self.paths.persona, {})
        write_json(self.paths.revisions, [])
        write_json(self.paths.review_items, [])
        self.touch_profile(self.profile_id)
