from __future__ import annotations

import os
import shutil
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .lifecycle import DEFAULT_AGING_POLICY
from .models import ConversationEvent, LongTermMemory, MemoryCandidate, MigrationRecord, PersonaProfile, ProfileMetadata, ProfileRegistry, ReviewItem, RevisionEntry, RuntimeSessionBinding
from .utils import copy_if_exists, detect_project_root, ensure_directory, read_json, read_json_strict, read_jsonl, slugify_text, stable_hash, utc_now, write_json, write_jsonl

SCHEMA_VERSION = 3
DEFAULT_PROFILE_ID = "default"
DEFAULT_BACKEND = "hybrid"
SNAPSHOT_RETENTION = 10
MutationScope = Literal["profile", "global"]
FLAT_DATA_FILES = {
    "conversations": "conversations.jsonl",
    "candidates": "memory_candidates.json",
    "long_term": "long_term_memory.json",
    "persona": "persona_profile.json",
    "revisions": "revisions.json",
    "review_items": "review_items.json",
}
PROFILE_DATA_FILES = {**FLAT_DATA_FILES, "candidate_archive": "candidate_archive.json"}
GLOBAL_DATA_FILES = {"registry": "registry.json", "migrations": "migrations.json", "runtime_sessions": "runtime_sessions.json"}


@dataclass(slots=True)
class StoragePaths:
    root: Path
    data_dir: Path
    registry: Path
    migrations: Path
    runtime_sessions: Path
    snapshots_dir: Path
    global_snapshots_dir: Path
    profiles_snapshots_dir: Path
    lock_path: Path
    profiles_dir: Path
    legacy_backup_dir: Path
    profile_dir: Path
    conversations: Path
    candidates: Path
    candidate_archive: Path
    long_term: Path
    persona: Path
    revisions: Path
    review_items: Path


class StorageBusyError(RuntimeError):
    pass


class SnapshotNotFoundError(RuntimeError):
    pass


class StorageCorruptError(RuntimeError):
    pass


@dataclass(slots=True)
class StorageMutationContext(AbstractContextManager["Storage"]):
    storage: "Storage"
    action: str
    scope: MutationScope
    profile_id: str | None = None

    def __enter__(self) -> "Storage":
        self.storage._enter_mutation(self.action, scope=self.scope, profile_id=self.profile_id)
        return self.storage

    def __exit__(self, exc_type, exc, tb) -> None:
        self.storage._exit_mutation()
        return None


class Storage:
    def __init__(self, root: Path | None = None, profile_id: str | None = None) -> None:
        self.root = detect_project_root(root)
        self.data_dir = ensure_directory(self.root / "data")
        self.registry_path = self.data_dir / GLOBAL_DATA_FILES["registry"]
        self.migrations_path = self.data_dir / GLOBAL_DATA_FILES["migrations"]
        self.runtime_sessions_path = self.data_dir / GLOBAL_DATA_FILES["runtime_sessions"]
        self.snapshots_dir = ensure_directory(self.data_dir / "snapshots")
        self.global_snapshots_dir = ensure_directory(self.snapshots_dir / "global")
        self.profile_snapshots_dir = ensure_directory(self.snapshots_dir / "profiles")
        self.lock_path = self.data_dir / ".storage.lock"
        self.profiles_dir = ensure_directory(self.data_dir / "profiles")
        self.legacy_backup_dir = ensure_directory(self.data_dir / "legacy_backup")
        self._mutation_depth = 0
        self._lock_fd: int | None = None
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
            runtime_sessions=self.runtime_sessions_path,
            snapshots_dir=self.snapshots_dir,
            global_snapshots_dir=self.global_snapshots_dir,
            profiles_snapshots_dir=self.profile_snapshots_dir,
            lock_path=self.lock_path,
            profiles_dir=self.profiles_dir,
            legacy_backup_dir=self.legacy_backup_dir,
            profile_dir=profile_dir,
            conversations=profile_dir / PROFILE_DATA_FILES["conversations"],
            candidates=profile_dir / PROFILE_DATA_FILES["candidates"],
            candidate_archive=profile_dir / PROFILE_DATA_FILES["candidate_archive"],
            long_term=profile_dir / PROFILE_DATA_FILES["long_term"],
            persona=profile_dir / PROFILE_DATA_FILES["persona"],
            revisions=profile_dir / PROFILE_DATA_FILES["revisions"],
            review_items=profile_dir / PROFILE_DATA_FILES["review_items"],
        )

    def _flat_legacy_files(self) -> dict[str, Path]:
        return {key: self.data_dir / filename for key, filename in FLAT_DATA_FILES.items() if (self.data_dir / filename).exists()}

    def _make_profile_metadata(self, profile_id: str, display_name: str) -> ProfileMetadata:
        timestamp = utc_now()
        return ProfileMetadata(id=profile_id, display_name=display_name, created_at=timestamp, updated_at=timestamp, backend=DEFAULT_BACKEND, aging_policy=DEFAULT_AGING_POLICY)

    def _ensure_layout(self) -> None:
        if self.registry_path.exists():
            if not self.migrations_path.exists():
                write_json(self.migrations_path, [])
            if not self.runtime_sessions_path.exists():
                write_json(self.runtime_sessions_path, [])
            return
        legacy_files = self._flat_legacy_files()
        if legacy_files:
            self._migrate_flat_storage(legacy_files)
            return
        registry = ProfileRegistry(schema_version=SCHEMA_VERSION, default_profile_id=DEFAULT_PROFILE_ID, profiles=[self._make_profile_metadata(DEFAULT_PROFILE_ID, "Default")])
        write_json(self.registry_path, registry.to_dict())
        write_json(self.migrations_path, [])
        write_json(self.runtime_sessions_path, [])
        self._ensure_profile_files(self._build_paths(DEFAULT_PROFILE_ID))

    def _migrate_flat_storage(self, legacy_files: dict[str, Path]) -> None:
        backup_dir = ensure_directory(self.legacy_backup_dir / "v1-flat")
        default_paths = self._build_paths(DEFAULT_PROFILE_ID)
        migrated_files: list[str] = []
        for source in legacy_files.values():
            migrated_files.append(source.name)
            backup_path = backup_dir / source.name
            target_path = default_paths.profile_dir / source.name
            if not backup_path.exists():
                copy_if_exists(source, backup_path)
            copy_if_exists(source, target_path)
            try:
                source.unlink()
            except OSError:
                pass
        if not default_paths.candidate_archive.exists():
            write_json(default_paths.candidate_archive, [])
        registry = ProfileRegistry(schema_version=SCHEMA_VERSION, default_profile_id=DEFAULT_PROFILE_ID, profiles=[self._make_profile_metadata(DEFAULT_PROFILE_ID, "Default")])
        write_json(self.registry_path, registry.to_dict())
        write_json(self.runtime_sessions_path, [])
        migration = MigrationRecord(id=f"migration_{stable_hash(f'flat-to-profile|{utc_now()}')}", name="flat-data-to-profiles", applied_at=utc_now(), status="applied", details={"source": "v1-flat", "profile_id": DEFAULT_PROFILE_ID, "files": migrated_files, "backup_dir": str(backup_dir)})
        write_json(self.migrations_path, [migration.to_dict()])
        self._ensure_profile_files(default_paths)

    def ensure_storage_files(self) -> None:
        self._ensure_profile_files(self.paths)
        if not self.runtime_sessions_path.exists():
            write_json(self.runtime_sessions_path, [])

    def _ensure_profile_files(self, paths: StoragePaths) -> None:
        ensure_directory(paths.profile_dir)
        if not paths.conversations.exists():
            write_jsonl(paths.conversations, [])
        if not paths.candidates.exists():
            write_json(paths.candidates, [])
        if not paths.candidate_archive.exists():
            write_json(paths.candidate_archive, [])
        if not paths.long_term.exists():
            write_json(paths.long_term, [])
        if not paths.persona.exists():
            write_json(paths.persona, {})
        if not paths.revisions.exists():
            write_json(paths.revisions, [])
        if not paths.review_items.exists():
            write_json(paths.review_items, [])

    def mutation(self, action: str, *, scope: MutationScope = "profile", profile_id: str | None = None) -> StorageMutationContext:
        return StorageMutationContext(self, action, scope, profile_id)

    def _enter_mutation(self, action: str, *, scope: MutationScope, profile_id: str | None = None) -> None:
        if self._mutation_depth == 0:
            self._acquire_lock(action)
            target_profile = profile_id or self.profile_id
            if scope == "profile":
                self._create_snapshot(action, scope="global", profile_id=None)
                self._create_snapshot(action, scope="profile", profile_id=target_profile)
            else:
                self._create_snapshot(action, scope=scope, profile_id=target_profile)
        self._mutation_depth += 1

    def _exit_mutation(self) -> None:
        self._mutation_depth = max(0, self._mutation_depth - 1)
        if self._mutation_depth == 0:
            self._release_lock()

    def _acquire_lock(self, action: str) -> None:
        ensure_directory(self.lock_path.parent)
        try:
            self._lock_fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(self._lock_fd, f"{os.getpid()}|{action}|{utc_now()}".encode("utf-8"))
        except FileExistsError as exc:
            raise StorageBusyError("Storage is busy; another write is already in progress.") from exc

    def _release_lock(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
        if self.lock_path.exists():
            try:
                self.lock_path.unlink()
            except OSError:
                pass

    def _snapshot_id(self, action: str) -> str:
        timestamp = utc_now().replace(":", "").replace("T", "-")
        return f"{timestamp}-{slugify_text(action, default='action')}"

    def _create_snapshot(self, action: str, *, scope: MutationScope, profile_id: str | None) -> None:
        snapshot_id = self._snapshot_id(action)
        if scope == "global":
            snapshot_dir = ensure_directory(self.global_snapshots_dir / snapshot_id)
            files = [self.registry_path, self.migrations_path, self.runtime_sessions_path]
        else:
            profile_key = profile_id or self.profile_id
            snapshot_root = ensure_directory(self.profile_snapshots_dir / profile_key)
            snapshot_dir = ensure_directory(snapshot_root / snapshot_id)
            paths = self._build_paths(profile_key)
            files = [paths.conversations, paths.candidates, paths.candidate_archive, paths.long_term, paths.persona, paths.review_items, paths.revisions]
        copied_files: list[str] = []
        for source in files:
            if source.exists():
                shutil.copy2(source, snapshot_dir / source.name)
                copied_files.append(source.name)
        write_json(snapshot_dir / "manifest.json", {"id": snapshot_id, "action": action, "scope": scope, "profile_id": profile_id, "created_at": utc_now(), "files": copied_files})
        self._prune_snapshot_dir(snapshot_dir.parent)

    def _prune_snapshot_dir(self, root: Path) -> None:
        snapshots = sorted((item for item in root.iterdir() if item.is_dir()), key=lambda item: item.name)
        while len(snapshots) > SNAPSHOT_RETENTION:
            shutil.rmtree(snapshots.pop(0), ignore_errors=True)

    def load_registry(self) -> ProfileRegistry:
        try:
            payload = read_json(self.registry_path, None)
        except Exception as exc:
            raise StorageCorruptError(f"Failed to read registry: {self.registry_path}") from exc
        if payload is None:
            registry = ProfileRegistry(schema_version=SCHEMA_VERSION, default_profile_id=DEFAULT_PROFILE_ID, profiles=[self._make_profile_metadata(DEFAULT_PROFILE_ID, "Default")])
            write_json(self.registry_path, registry.to_dict())
            return registry
        registry = ProfileRegistry.from_dict(payload)
        if registry.schema_version < SCHEMA_VERSION:
            registry.schema_version = SCHEMA_VERSION
            write_json(self.registry_path, registry.to_dict())
        return registry

    def save_registry(self, registry: ProfileRegistry) -> None:
        self.registry = registry
        write_json(self.registry_path, registry.to_dict())

    def load_migrations(self) -> list[MigrationRecord]:
        try:
            payload = read_json(self.migrations_path, [])
        except Exception as exc:
            raise StorageCorruptError(f"Failed to read migrations: {self.migrations_path}") from exc
        return [MigrationRecord.from_dict(item) for item in payload or []]

    def append_migrations(self, records: list[MigrationRecord]) -> None:
        if not records:
            return
        existing = self.load_migrations()
        existing.extend(records)
        write_json(self.migrations_path, [record.to_dict() for record in existing])

    def migration_status(self) -> dict[str, Any]:
        migrations = self.load_migrations()
        return {"schema_version": self.registry.schema_version, "default_profile_id": self.registry.default_profile_id, "profiles": [profile.id for profile in self.registry.profiles], "last_migration": migrations[-1].to_dict() if migrations else None}

    def list_profiles(self) -> list[ProfileMetadata]:
        return list(self.registry.profiles)

    def get_profile_metadata(self, profile_id: str | None = None) -> ProfileMetadata | None:
        target = profile_id or self.profile_id
        for profile in self.registry.profiles:
            if profile.id == target:
                return profile
        return None

    def create_profile(self, profile_id: str, *, display_name: str | None = None, backend: str = DEFAULT_BACKEND, aging_policy: str = DEFAULT_AGING_POLICY) -> ProfileMetadata:
        normalized_id = slugify_text(profile_id, default="profile")
        if self.get_profile_metadata(normalized_id) is not None:
            raise ValueError(f"Profile {normalized_id} already exists.")
        profile = ProfileMetadata(id=normalized_id, display_name=display_name or normalized_id, created_at=utc_now(), updated_at=utc_now(), backend=backend, aging_policy=aging_policy)
        context = self.mutation("create-profile", scope="global", profile_id=normalized_id) if self._mutation_depth == 0 else None
        if context is not None:
            context.__enter__()
        try:
            self.registry.profiles.append(profile)
            self.save_registry(self.registry)
            self._ensure_profile_files(self._build_paths(normalized_id))
        finally:
            if context is not None:
                context.__exit__(None, None, None)
        return profile

    def set_default_profile(self, profile_id: str) -> ProfileMetadata:
        profile = self.get_profile_metadata(profile_id)
        if profile is None:
            raise ValueError(f"Profile {profile_id} not found.")
        context = self.mutation("set-default-profile", scope="global", profile_id=profile_id) if self._mutation_depth == 0 else None
        if context is not None:
            context.__enter__()
        try:
            self.registry.default_profile_id = profile_id
            self.save_registry(self.registry)
        finally:
            if context is not None:
                context.__exit__(None, None, None)
        return profile

    def touch_profile(self, profile_id: str, *, backend: str | None = None, aging_policy: str | None = None) -> ProfileMetadata:
        profile = self.get_profile_metadata(profile_id)
        if profile is None:
            raise ValueError(f"Profile {profile_id} not found.")
        profile.updated_at = utc_now()
        if backend:
            profile.backend = backend
        if aging_policy:
            profile.aging_policy = aging_policy
        self.save_registry(self.registry)
        return profile

    def load_conversation_events(self) -> list[ConversationEvent]:
        try:
            payload = read_jsonl(self.paths.conversations)
        except Exception as exc:
            raise StorageCorruptError(f"Failed to read conversation events: {self.paths.conversations}") from exc
        return [ConversationEvent.from_dict(item) for item in payload]

    def save_conversation_events(self, events: list[ConversationEvent]) -> None:
        write_jsonl(self.paths.conversations, [event.to_dict() for event in events])

    def append_conversation_events(self, events: list[ConversationEvent]) -> list[ConversationEvent]:
        existing = self.load_conversation_events()
        known_ids = {event.id for event in existing}
        additions = [event for event in events if event.id not in known_ids]
        if additions:
            self.save_conversation_events(existing + additions)
        return additions

    def load_memory_candidates(self) -> list[MemoryCandidate]:
        try:
            payload = read_json(self.paths.candidates, [])
        except Exception as exc:
            raise StorageCorruptError(f"Failed to read memory candidates: {self.paths.candidates}") from exc
        return [MemoryCandidate.from_dict(item) for item in payload or []]

    def save_memory_candidates(self, candidates: list[MemoryCandidate]) -> None:
        write_json(self.paths.candidates, [candidate.to_dict() for candidate in candidates])

    def load_candidate_archive(self) -> list[MemoryCandidate]:
        try:
            payload = read_json(self.paths.candidate_archive, [])
        except Exception as exc:
            raise StorageCorruptError(f"Failed to read candidate archive: {self.paths.candidate_archive}") from exc
        return [MemoryCandidate.from_dict(item) for item in payload or []]

    def save_candidate_archive(self, candidates: list[MemoryCandidate]) -> None:
        write_json(self.paths.candidate_archive, [candidate.to_dict() for candidate in candidates])

    def load_long_term_memory(self) -> list[LongTermMemory]:
        try:
            payload = read_json(self.paths.long_term, [])
        except Exception as exc:
            raise StorageCorruptError(f"Failed to read long-term memory: {self.paths.long_term}") from exc
        return [LongTermMemory.from_dict(item) for item in payload or []]

    def save_long_term_memory(self, memories: list[LongTermMemory]) -> None:
        write_json(self.paths.long_term, [memory.to_dict() for memory in memories])

    def load_persona_profile(self) -> PersonaProfile | None:
        try:
            payload = read_json(self.paths.persona, {})
        except Exception as exc:
            raise StorageCorruptError(f"Failed to read persona profile: {self.paths.persona}") from exc
        if not payload:
            return None
        return PersonaProfile.from_dict(payload)

    def save_persona_profile(self, profile: PersonaProfile | None) -> None:
        write_json(self.paths.persona, {} if profile is None else profile.to_dict())

    def load_review_items(self) -> list[ReviewItem]:
        try:
            payload = read_json(self.paths.review_items, [])
        except Exception as exc:
            raise StorageCorruptError(f"Failed to read review items: {self.paths.review_items}") from exc
        return [ReviewItem.from_dict(item) for item in payload or []]

    def save_review_items(self, review_items: list[ReviewItem]) -> None:
        write_json(self.paths.review_items, [item.to_dict() for item in review_items])

    def load_revisions(self) -> list[RevisionEntry]:
        try:
            payload = read_json(self.paths.revisions, [])
        except Exception as exc:
            raise StorageCorruptError(f"Failed to read revisions: {self.paths.revisions}") from exc
        return [RevisionEntry.from_dict(item) for item in payload or []]

    def append_revisions(self, revisions: list[RevisionEntry]) -> None:
        if not revisions:
            return
        existing = self.load_revisions()
        existing.extend(revisions)
        write_json(self.paths.revisions, [revision.to_dict() for revision in existing])

    def load_runtime_sessions(self) -> list[RuntimeSessionBinding]:
        try:
            payload = read_json(self.runtime_sessions_path, [])
        except Exception as exc:
            raise StorageCorruptError(f"Failed to read runtime sessions: {self.runtime_sessions_path}") from exc
        return [RuntimeSessionBinding.from_dict(item) for item in payload or []]

    def save_runtime_sessions(self, bindings: list[RuntimeSessionBinding]) -> None:
        write_json(self.runtime_sessions_path, [binding.to_dict() for binding in bindings])

    def get_runtime_session_binding(self, session_id: str) -> RuntimeSessionBinding | None:
        for binding in self.load_runtime_sessions():
            if binding.session_id == session_id:
                return binding
        return None

    def upsert_runtime_session_binding(self, session_id: str, profile_id: str, *, last_action: str, closed_at: str | None = None) -> RuntimeSessionBinding:
        bindings = self.load_runtime_sessions()
        timestamp = utc_now()
        match: RuntimeSessionBinding | None = None
        for binding in bindings:
            if binding.session_id == session_id:
                match = binding
                break
        if match is None:
            match = RuntimeSessionBinding(session_id=session_id, profile_id=profile_id, created_at=timestamp, last_seen=timestamp, last_action=last_action, closed_at=closed_at)
            bindings.append(match)
        else:
            match.profile_id = profile_id
            match.last_seen = timestamp
            match.last_action = last_action
            match.closed_at = closed_at
        self.save_runtime_sessions(bindings)
        return match

    def close_runtime_session(self, session_id: str) -> RuntimeSessionBinding | None:
        bindings = self.load_runtime_sessions()
        for binding in bindings:
            if binding.session_id == session_id:
                binding.last_seen = utc_now()
                binding.last_action = "close_session"
                binding.closed_at = utc_now()
                self.save_runtime_sessions(bindings)
                return binding
        return None

    def export_all_profiles_state(self) -> dict[str, Any]:
        snapshots: dict[str, Any] = {}
        for profile in self.registry.profiles:
            scoped = Storage(self.root, profile.id)
            persona = scoped.load_persona_profile()
            snapshots[profile.id] = {
                "profile": profile.to_dict(),
                "conversation_events": [event.to_dict() for event in scoped.load_conversation_events()],
                "memory_candidates": [candidate.to_dict() for candidate in scoped.load_memory_candidates()],
                "candidate_archive": [candidate.to_dict() for candidate in scoped.load_candidate_archive()],
                "long_term_memory": [memory.to_dict() for memory in scoped.load_long_term_memory()],
                "persona_profile": persona.to_dict() if persona else {},
                "review_items": [item.to_dict() for item in scoped.load_review_items()],
                "revisions": [revision.to_dict() for revision in scoped.load_revisions()],
            }
        return snapshots

    def list_snapshots(self, *, scope: MutationScope | None = None, profile_id: str | None = None) -> list[dict[str, Any]]:
        manifests: list[dict[str, Any]] = []
        if scope in {None, "global"}:
            manifests.extend(self._snapshot_manifests(self.global_snapshots_dir))
        if scope in {None, "profile"}:
            if profile_id:
                manifests.extend(self._snapshot_manifests(self.profile_snapshots_dir / profile_id))
            else:
                for child in sorted((item for item in self.profile_snapshots_dir.iterdir() if item.is_dir()), key=lambda item: item.name):
                    manifests.extend(self._snapshot_manifests(child))
        manifests.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return manifests

    def _snapshot_manifests(self, root: Path) -> list[dict[str, Any]]:
        if not root.exists():
            return []
        manifests: list[dict[str, Any]] = []
        for child in root.iterdir():
            if not child.is_dir():
                continue
            manifest_path = child / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                payload = read_json_strict(manifest_path)
            except Exception as exc:
                raise StorageCorruptError(f"Failed to read snapshot manifest: {manifest_path}") from exc
            payload["path"] = str(child)
            manifests.append(payload)
        return manifests

    def restore_snapshot(self, snapshot_id: str, *, profile_id: str | None = None) -> dict[str, Any]:
        manifest, snapshot_dir = self._find_snapshot(snapshot_id, profile_id=profile_id)
        scope = manifest["scope"]
        if scope == "global":
            files = [self.registry_path, self.migrations_path, self.runtime_sessions_path]
        else:
            target_profile = manifest.get("profile_id") or profile_id or self.profile_id
            paths = self._build_paths(target_profile)
            files = [paths.conversations, paths.candidates, paths.candidate_archive, paths.long_term, paths.persona, paths.review_items, paths.revisions]
        copied: list[str] = []
        for target in files:
            source = snapshot_dir / target.name
            if source.exists():
                shutil.copy2(source, target)
                copied.append(target.name)
        self.registry = self.load_registry()
        self.append_migrations([MigrationRecord(id=f"migration_{stable_hash(f'restore-snapshot|{snapshot_id}|{utc_now()}')}", name="restore-snapshot", applied_at=utc_now(), status="applied", details={"snapshot_id": snapshot_id, "scope": scope, "profile_id": manifest.get("profile_id"), "files": copied})])
        if scope == "profile":
            target_profile = manifest.get("profile_id") or profile_id or self.profile_id
            scoped = Storage(self.root, target_profile)
            scoped.append_revisions([RevisionEntry(id=f"rev_{stable_hash(f'restore-snapshot|{target_profile}|{snapshot_id}|{utc_now()}')}", entity_type="storage_snapshot", entity_id=snapshot_id, action="restore_snapshot", timestamp=utc_now(), reason=f"Restored snapshot {snapshot_id}", before=None, after={"snapshot_id": snapshot_id, "scope": scope, "profile_id": target_profile})])
        return {"snapshot_id": snapshot_id, "scope": scope, "profile_id": manifest.get("profile_id"), "files_restored": copied}

    def _find_snapshot(self, snapshot_id: str, *, profile_id: str | None = None) -> tuple[dict[str, Any], Path]:
        for manifest in self.list_snapshots(scope="profile" if profile_id else None, profile_id=profile_id):
            if manifest.get("id") == snapshot_id:
                return manifest, Path(manifest["path"])
        raise SnapshotNotFoundError(f"Snapshot {snapshot_id} not found.")

    def storage_health(self, profile_id: str | None = None) -> dict[str, Any]:
        issues: list[str] = []
        checks: list[dict[str, Any]] = []

        def record(name: str, passed: bool, detail: str = "") -> None:
            checks.append({"name": name, "passed": passed, "detail": detail})
            if not passed:
                issues.append(f"{name}: {detail}".strip())

        try:
            read_json_strict(self.registry_path)
            read_json_strict(self.migrations_path)
            read_json_strict(self.runtime_sessions_path)
            record("global_json", True)
        except Exception as exc:
            record("global_json", False, str(exc))

        known_profiles = {profile.id for profile in self.registry.profiles}
        bad_runtime_refs = [binding.session_id for binding in self.load_runtime_sessions() if binding.profile_id not in known_profiles]
        record("runtime_session_profile_reference", not bad_runtime_refs, ", ".join(sorted(bad_runtime_refs)))

        targets = [profile_id] if profile_id else [profile.id for profile in self.registry.profiles]
        for target_profile in targets:
            if target_profile not in known_profiles:
                record(f"profile_exists:{target_profile}", False, "missing profile")
                continue
            scoped = Storage(self.root, target_profile)
            try:
                active_candidates = scoped.load_memory_candidates()
                archived_candidates = scoped.load_candidate_archive()
                memories = scoped.load_long_term_memory()
                reviews = scoped.load_review_items()
                scoped.load_conversation_events()
                scoped.load_revisions()
                persona = scoped.load_persona_profile()
                if persona is not None:
                    persona.to_dict()
                record(f"profile_json:{target_profile}", True)
            except Exception as exc:
                record(f"profile_json:{target_profile}", False, str(exc))
                continue
            overlap = {candidate.id for candidate in active_candidates} & {candidate.id for candidate in archived_candidates}
            record(f"candidate_overlap:{target_profile}", not overlap, ", ".join(sorted(overlap)))
            candidate_ids = {candidate.id for candidate in active_candidates} | {candidate.id for candidate in archived_candidates}
            memory_ids = {memory.id for memory in memories}
            bad_reviews = [item.id for item in reviews if item.candidate_id not in candidate_ids or (item.target_memory_id is not None and item.target_memory_id not in memory_ids)]
            record(f"review_references:{target_profile}", not bad_reviews, ", ".join(sorted(bad_reviews)))

        missing_manifests = [manifest.get("id", "unknown") for manifest in self.list_snapshots() if not (Path(manifest["path"]) / "manifest.json").exists()]
        record("snapshot_manifests", not missing_manifests, ", ".join(missing_manifests))
        return {"ok": not issues, "issues": issues, "checks": checks, "profile_ids": targets, "snapshot_count": len(self.list_snapshots())}

    def reset(self) -> None:
        with self.mutation("reset-profile", scope="profile", profile_id=self.profile_id):
            self.save_conversation_events([])
            self.save_memory_candidates([])
            self.save_candidate_archive([])
            self.save_long_term_memory([])
            self.save_persona_profile(None)
            self.save_review_items([])
            write_json(self.paths.revisions, [])
