from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TextIO

from .candidate_lifecycle import refresh_candidate_collections
from .cli import build_export_markdown, load_dialogue_payload, normalize_dialogue_payload
from .consolidator import MemoryConsolidator
from .extractor import MemoryExtractor
from .operations import (
    archive_candidates_action,
    build_persona_profile,
    consolidate_profile,
    current_reference_time,
    export_payload,
    extract_candidates,
    forget_memory,
    ingest_payload,
    list_candidates_payload,
    list_snapshots_payload,
    prepare_context_bundle,
    reopen_candidate_action,
    resolve_backend,
    resolve_review_action,
    restore_candidate_action,
    restore_snapshot_action,
    retrieve_context_bundle,
    revise_memory,
    show_candidate_payload,
    storage_health_payload,
)
from .persona_builder import PersonaBuilder
from .retrieval import RetrievalService
from .storage import DEFAULT_BACKEND, SCHEMA_VERSION, SnapshotNotFoundError, Storage, StorageBusyError, StorageCorruptError
from .utils import sort_timestamp, utc_now, write_json

RUNTIME_SCHEMA_VERSION = 2
NATIVE_ACTIONS = ["hello", "open_session", "close_session", "step"]
MIRROR_ACTIONS = [
    "migrate_storage", "list_profiles", "create_profile", "show_profile", "set_default_profile",
    "ingest", "extract", "consolidate", "build_persona", "retrieve_context", "prepare_context",
    "show_memory", "show_persona", "list_review", "show_review", "resolve_review",
    "reopen_candidate", "list_candidates", "show_candidate", "restore_candidate", "archive_candidates",
    "list_snapshots", "restore_snapshot", "storage_health", "forget", "revise", "replay_eval", "export",
]
SUPPORTED_ACTIONS = [*NATIVE_ACTIONS, *MIRROR_ACTIONS]
RUNTIME_CAPABILITIES = ["session_runtime", "full_cli_mirror", "persist_then_retrieve", "profile_binding", "jsonl_transport", "candidate_archive", "storage_snapshots"]


class RuntimeProtocolError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(slots=True)
class RuntimeRequest:
    id: str | None
    action: str
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Any) -> "RuntimeRequest":
        if not isinstance(payload, dict):
            raise RuntimeProtocolError("invalid_params", "Runtime request must be a JSON object.")
        action = payload.get("action")
        if not isinstance(action, str) or not action.strip():
            raise RuntimeProtocolError("invalid_params", "Runtime request requires a non-empty string 'action'.")
        params = payload.get("params", {}) or {}
        if not isinstance(params, dict):
            raise RuntimeProtocolError("invalid_params", "Runtime request 'params' must be an object when provided.")
        request_id = payload.get("id")
        if request_id is not None and not isinstance(request_id, str):
            raise RuntimeProtocolError("invalid_params", "Runtime request 'id' must be a string when provided.")
        return cls(id=request_id, action=action, params=params)


@dataclass(slots=True)
class RuntimeErrorPayload:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


@dataclass(slots=True)
class RuntimeResponse:
    id: str | None
    ok: bool
    result: Any = None
    error: RuntimeErrorPayload | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": self.id, "ok": self.ok}
        if self.ok:
            payload["result"] = self.result
        else:
            payload["error"] = self.error.to_dict() if self.error is not None else None
        return payload


@dataclass(slots=True)
class RuntimeHello:
    schema_version: int
    runtime_schema_version: int
    capabilities: list[str]
    supported_actions: list[str]
    default_profile_id: str

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "runtime_schema_version": self.runtime_schema_version, "capabilities": list(self.capabilities), "supported_actions": list(self.supported_actions), "default_profile_id": self.default_profile_id}


@dataclass(slots=True)
class RuntimeStepResult:
    session: dict[str, Any]
    write_summary: dict[str, Any]
    context: dict[str, Any]
    persona_snapshot: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"session": dict(self.session), "write_summary": dict(self.write_summary), "context": dict(self.context), "persona_snapshot": dict(self.persona_snapshot)}


class SessionRuntime:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Storage(root).root if root is not None else Storage().root
        self.extractor = MemoryExtractor()
        self._dispatch: dict[str, Callable[[dict[str, Any]], Any]] = {
            "hello": self._action_hello,
            "open_session": self._action_open_session,
            "close_session": self._action_close_session,
            "step": self._action_step,
            "migrate_storage": self._action_migrate_storage,
            "list_profiles": self._action_list_profiles,
            "create_profile": self._action_create_profile,
            "show_profile": self._action_show_profile,
            "set_default_profile": self._action_set_default_profile,
            "ingest": self._action_ingest,
            "extract": self._action_extract,
            "consolidate": self._action_consolidate,
            "build_persona": self._action_build_persona,
            "retrieve_context": self._action_retrieve_context,
            "prepare_context": self._action_prepare_context,
            "show_memory": self._action_show_memory,
            "show_persona": self._action_show_persona,
            "list_review": self._action_list_review,
            "show_review": self._action_show_review,
            "resolve_review": self._action_resolve_review,
            "reopen_candidate": self._action_reopen_candidate,
            "list_candidates": self._action_list_candidates,
            "show_candidate": self._action_show_candidate,
            "restore_candidate": self._action_restore_candidate,
            "archive_candidates": self._action_archive_candidates,
            "list_snapshots": self._action_list_snapshots,
            "restore_snapshot": self._action_restore_snapshot,
            "storage_health": self._action_storage_health,
            "forget": self._action_forget,
            "revise": self._action_revise,
            "replay_eval": self._action_replay_eval,
            "export": self._action_export,
        }

    def serve(self, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
        input_stream = stdin or sys.stdin
        output_stream = stdout or sys.stdout
        for raw_line in input_stream:
            line = raw_line.strip()
            if not line:
                continue
            output_stream.write(json.dumps(self.handle_line(line), ensure_ascii=False) + "\n")
            output_stream.flush()
        return 0

    def handle_line(self, line: str) -> dict[str, Any]:
        request_id: str | None = None
        try:
            payload = json.loads(line)
            request_id = payload.get("id") if isinstance(payload, dict) else None
            request = RuntimeRequest.from_payload(payload)
            return RuntimeResponse(id=request.id, ok=True, result=self.dispatch(request.action, request.params)).to_dict()
        except RuntimeProtocolError as exc:
            return RuntimeResponse(id=request_id, ok=False, error=RuntimeErrorPayload(exc.code, exc.message, exc.details)).to_dict()
        except Exception as exc:
            return RuntimeResponse(id=request_id, ok=False, error=self._map_exception(exc)).to_dict()

    def dispatch(self, action: str, params: dict[str, Any]) -> Any:
        handler = self._dispatch.get(action)
        if handler is None:
            raise RuntimeProtocolError("invalid_action", f"Unsupported runtime action: {action}", {"supported_actions": SUPPORTED_ACTIONS})
        return handler(params)

    def _base_storage(self) -> Storage:
        return Storage(self.root)

    def _profile_storage(self, profile_id: str | None = None) -> Storage:
        return Storage(self.root, profile_id=profile_id)

    def _resolve_profile(self, *, profile_id: str | None, session_id: str | None) -> tuple[str, str]:
        base = self._base_storage()
        if profile_id is not None:
            if base.get_profile_metadata(profile_id) is None:
                raise RuntimeProtocolError("profile_not_found", f"Profile {profile_id} not found.", {"profile_id": profile_id})
            return profile_id, "explicit"
        if session_id:
            binding = base.get_runtime_session_binding(session_id)
            if binding is not None:
                if base.get_profile_metadata(binding.profile_id) is None:
                    raise RuntimeProtocolError("profile_not_found", f"Session {session_id} is bound to missing profile {binding.profile_id}.", {"session_id": session_id, "profile_id": binding.profile_id})
                return binding.profile_id, "existing_binding"
        default_profile_id = base.registry.default_profile_id
        if base.get_profile_metadata(default_profile_id) is None:
            raise RuntimeProtocolError("profile_not_found", f"Default profile {default_profile_id} not found.", {"profile_id": default_profile_id})
        return default_profile_id, "default_fallback"

    def _resolve_storage_from_params(self, params: dict[str, Any]) -> tuple[Storage, str]:
        profile_id = self._optional_string(params, "profile_id")
        session_id = self._optional_string(params, "session_id")
        resolved_profile_id, source = self._resolve_profile(profile_id=profile_id, session_id=session_id)
        return self._profile_storage(resolved_profile_id), source

    def _action_hello(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        base = self._base_storage()
        return RuntimeHello(schema_version=SCHEMA_VERSION, runtime_schema_version=RUNTIME_SCHEMA_VERSION, capabilities=list(RUNTIME_CAPABILITIES), supported_actions=list(SUPPORTED_ACTIONS), default_profile_id=base.registry.default_profile_id).to_dict()

    def _action_open_session(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = self._require_string(params, "session_id")
        requested_profile_id = self._optional_string(params, "profile_id")
        profile_id, source = self._resolve_profile(profile_id=requested_profile_id, session_id=session_id)
        base = self._base_storage()
        with base.mutation("open-session", scope="global", profile_id=profile_id):
            binding = base.upsert_runtime_session_binding(session_id, profile_id, last_action="open_session", closed_at=None)
        return {"session_id": binding.session_id, "profile_id": binding.profile_id, "binding_source": source, "created_at": binding.created_at, "last_seen": binding.last_seen, "closed_at": binding.closed_at}

    def _action_close_session(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = self._require_string(params, "session_id")
        base = self._base_storage()
        with base.mutation("close-session", scope="global"):
            binding = base.close_runtime_session(session_id)
        if binding is None:
            raise RuntimeProtocolError("session_not_found", f"Session {session_id} not found.", {"session_id": session_id})
        return binding.to_dict()

    def _action_step(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = self._require_string(params, "session_id")
        query = self._require_string(params, "query")
        messages = params.get("messages")
        if not isinstance(messages, list):
            raise RuntimeProtocolError("invalid_params", "Step requires 'messages' as a list.")
        top_k = self._optional_int(params, "top_k", 5)
        include_contested = self._optional_bool(params, "include_contested", True)
        include_review = self._optional_bool(params, "include_review", True)
        requested_profile_id = self._optional_string(params, "profile_id")
        profile_id, source = self._resolve_profile(profile_id=requested_profile_id, session_id=session_id)
        storage = self._profile_storage(profile_id)
        profile = storage.get_profile_metadata(profile_id)
        try:
            events = normalize_dialogue_payload([{"session_id": session_id, "messages": messages}])
        except ValueError as exc:
            raise RuntimeProtocolError("invalid_params", str(exc), {"field": "messages"}) from exc
        with storage.mutation("step", scope="profile", profile_id=profile_id):
            added_events = storage.append_conversation_events(events)
            active = storage.load_memory_candidates()
            archived = storage.load_candidate_archive()
            extracted = self.extractor.extract_from_events(added_events, existing_candidates=active, archived_candidates=archived) if added_events else []
            id_index = {candidate.id: candidate for candidate in active}
            for candidate in extracted:
                id_index[candidate.id] = candidate
            storage.save_memory_candidates(sorted(id_index.values(), key=lambda item: (sort_timestamp(item.created_at), item.id)))
            reference = current_reference_time(storage)
            rebuilt = self.extractor.extract_from_events(storage.load_conversation_events(), existing_candidates=storage.load_memory_candidates(), archived_candidates=storage.load_candidate_archive())
            refresh = refresh_candidate_collections(rebuilt, storage.load_candidate_archive(), reference_time=reference)
            storage.save_memory_candidates(refresh.active_candidates)
            storage.save_candidate_archive(refresh.archived_candidates)
            backend_name = resolve_backend(storage, None)
            consolidation = MemoryConsolidator(backend_name=backend_name, aging_policy=profile.aging_policy).consolidate(refresh.active_candidates, storage.load_long_term_memory(), storage.load_review_items(), reference_time=reference)
            consolidation.candidates_archived = refresh.archived_count
            storage.save_memory_candidates(consolidation.candidates)
            storage.save_candidate_archive(refresh.archived_candidates)
            storage.save_long_term_memory(consolidation.memories)
            storage.save_review_items(consolidation.review_items)
            if consolidation.revisions:
                storage.append_revisions(consolidation.revisions)
            storage.touch_profile(profile_id, backend=backend_name)
            persona = PersonaBuilder(aging_policy=profile.aging_policy).build(consolidation.memories, reference_time=reference)
            storage.save_long_term_memory(consolidation.memories)
            storage.save_persona_profile(persona)
            context = RetrievalService(backend_name=backend_name, aging_policy=profile.aging_policy).retrieve(query=query, memories=consolidation.memories, review_items=consolidation.review_items, profile_id=profile_id, top_k=max(0, top_k), include_contested=include_contested, include_review=include_review, reference_time=reference)
            storage.save_long_term_memory(consolidation.memories)
        base = self._base_storage()
        with base.mutation("step-session-binding", scope="global", profile_id=profile_id):
            base.upsert_runtime_session_binding(session_id, profile_id, last_action="step", closed_at=None)
        return RuntimeStepResult(session={"session_id": session_id, "profile_id": profile_id, "binding_source": source}, write_summary={"events_added": len(added_events), "candidates_rebuilt": len(rebuilt), "created": consolidation.created, "updated": consolidation.updated, "conflicts": consolidation.conflicts, "pending": consolidation.pending, "candidates_archived": consolidation.candidates_archived, "candidates_restored": 0, "persona_rebuilt": True}, context=context.to_dict(), persona_snapshot=self._persona_snapshot(persona)).to_dict()

    def _action_migrate_storage(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        storage = self._base_storage()
        payload = storage.migration_status()
        payload["migrations"] = [item.to_dict() for item in storage.load_migrations()]
        return payload

    def _action_list_profiles(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        storage = self._base_storage()
        return {"schema_version": storage.registry.schema_version, "default_profile_id": storage.registry.default_profile_id, "profiles": [profile.to_dict() for profile in storage.list_profiles()]}

    def _action_create_profile(self, params: dict[str, Any]) -> dict[str, Any]:
        storage = self._base_storage()
        profile = storage.create_profile(self._require_string(params, "profile_id"), display_name=self._optional_string(params, "display_name"), backend=self._optional_string(params, "backend") or DEFAULT_BACKEND, aging_policy=self._optional_string(params, "aging_policy") or "default-v1")
        if self._optional_bool(params, "set_default", False):
            storage.set_default_profile(profile.id)
        return {"profile": profile.to_dict(), "default_profile_id": storage.registry.default_profile_id}

    def _action_show_profile(self, params: dict[str, Any]) -> dict[str, Any]:
        requested_profile = self._optional_string(params, "profile_id")
        if requested_profile is not None:
            storage = self._profile_storage(requested_profile)
            source = "explicit"
        else:
            storage, source = self._resolve_storage_from_params(params)
        profile = storage.get_profile_metadata()
        if profile is None:
            raise RuntimeProtocolError("profile_not_found", f"Profile {storage.profile_id} not found.", {"profile_id": storage.profile_id})
        return {"schema_version": storage.registry.schema_version, "default_profile_id": storage.registry.default_profile_id, "binding_source": source, "profile": profile.to_dict()}

    def _action_set_default_profile(self, params: dict[str, Any]) -> dict[str, Any]:
        profile = self._base_storage().set_default_profile(self._require_string(params, "profile_id"))
        return {"default_profile_id": self._base_storage().registry.default_profile_id, "profile": profile.to_dict()}

    def _action_ingest(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, source = self._resolve_storage_from_params(params)
        payload = params.get("payload")
        path_value = self._optional_string(params, "path")
        source_path: str | None = None
        if payload is None:
            if path_value is None:
                raise RuntimeProtocolError("invalid_params", "Ingest requires either 'path' or 'payload'.")
            source_path = str(self._resolve_path(path_value))
            payload = load_dialogue_payload(Path(source_path))
        try:
            events = normalize_dialogue_payload(payload)
        except ValueError as exc:
            raise RuntimeProtocolError("invalid_params", str(exc), {"action": "ingest"}) from exc
        result = ingest_payload(storage, payload, events=events)
        result.update({"profile_id": storage.profile_id, "binding_source": source, "source_path": source_path})
        return result

    def _action_extract(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, source = self._resolve_storage_from_params(params)
        result = extract_candidates(storage)
        result.update({"profile_id": storage.profile_id, "binding_source": source})
        return result

    def _action_consolidate(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, source = self._resolve_storage_from_params(params)
        payload = consolidate_profile(storage, backend_override=self._optional_string(params, "backend"))
        result = payload["result"]
        return {"profile_id": storage.profile_id, "binding_source": source, "backend": payload["backend"], "created": result.created, "updated": result.updated, "conflicts": result.conflicts, "pending": result.pending, "candidates_archived": result.candidates_archived, "candidates_restored": result.candidates_restored}

    def _action_build_persona(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, source = self._resolve_storage_from_params(params)
        persona = build_persona_profile(storage)
        return {"profile_id": storage.profile_id, "binding_source": source, "persona_profile": persona.to_dict()}

    def _action_retrieve_context(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, _ = self._resolve_storage_from_params(params)
        result = retrieve_context_bundle(storage, query=self._require_string(params, "query"), top_k=self._optional_int(params, "top_k", 5), include_contested=self._optional_bool(params, "include_contested", True), include_review=self._optional_bool(params, "include_review", True), backend_override=self._optional_string(params, "backend"))
        return result.to_dict()

    def _action_prepare_context(self, params: dict[str, Any]) -> str:
        storage, _ = self._resolve_storage_from_params(params)
        _, markdown = prepare_context_bundle(storage, query=self._require_string(params, "query"), top_k=self._optional_int(params, "top_k", 5), include_contested=self._optional_bool(params, "include_contested", True), include_review=self._optional_bool(params, "include_review", True), backend_override=self._optional_string(params, "backend"))
        return markdown

    def _action_show_memory(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, source = self._resolve_storage_from_params(params)
        memories = storage.load_long_term_memory()
        if not self._optional_bool(params, "include_inactive", False):
            memories = [memory for memory in memories if memory.active]
        return {"profile_id": storage.profile_id, "binding_source": source, "long_term_memory": [memory.to_dict() for memory in memories]}

    def _action_show_persona(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, source = self._resolve_storage_from_params(params)
        persona = storage.load_persona_profile()
        return {"profile_id": storage.profile_id, "binding_source": source, "persona_profile": persona.to_dict() if persona is not None else None}

    def _action_list_review(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, source = self._resolve_storage_from_params(params)
        status = self._optional_string(params, "status")
        review_items = storage.load_review_items()
        if status is not None:
            review_items = [item for item in review_items if item.status == status]
        review_items.sort(key=lambda item: (sort_timestamp(item.opened_at), item.id))
        return {"profile_id": storage.profile_id, "binding_source": source, "review_items": [item.to_dict() for item in review_items]}

    def _action_show_review(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, source = self._resolve_storage_from_params(params)
        review_id = self._require_string(params, "review_id")
        review = next((item for item in storage.load_review_items() if item.id == review_id), None)
        if review is None:
            raise RuntimeProtocolError("review_not_found", f"Review item {review_id} not found.", {"review_id": review_id})
        return {"profile_id": storage.profile_id, "binding_source": source, "review_item": review.to_dict()}

    def _action_resolve_review(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, source = self._resolve_storage_from_params(params)
        result = resolve_review_action(storage, review_id=self._require_string(params, "review_id"), action=self._require_string(params, "action"), reason=self._require_string(params, "reason"), memory_id=self._optional_string(params, "memory_id"))
        result.update({"profile_id": storage.profile_id, "binding_source": source})
        return result

    def _action_reopen_candidate(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, source = self._resolve_storage_from_params(params)
        result = reopen_candidate_action(storage, candidate_id=self._require_string(params, "candidate_id"), reason=self._require_string(params, "reason"))
        result.update({"profile_id": storage.profile_id, "binding_source": source})
        return result

    def _action_list_candidates(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, source = self._resolve_storage_from_params(params)
        payload = list_candidates_payload(storage, include_archived=self._optional_bool(params, "include_archived", False), status=self._optional_string(params, "status"), lifecycle_state=self._optional_string(params, "lifecycle_state"))
        payload.update({"profile_id": storage.profile_id, "binding_source": source})
        return payload

    def _action_show_candidate(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, source = self._resolve_storage_from_params(params)
        payload = show_candidate_payload(storage, candidate_id=self._require_string(params, "candidate_id"))
        payload.update({"profile_id": storage.profile_id, "binding_source": source})
        return payload

    def _action_restore_candidate(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, source = self._resolve_storage_from_params(params)
        payload = restore_candidate_action(storage, candidate_id=self._require_string(params, "candidate_id"), reason=self._require_string(params, "reason"))
        payload.update({"profile_id": storage.profile_id, "binding_source": source})
        return payload

    def _action_archive_candidates(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, source = self._resolve_storage_from_params(params)
        candidate_ids = params.get("candidate_ids", []) or []
        if not isinstance(candidate_ids, list) or any(not isinstance(item, str) for item in candidate_ids):
            raise RuntimeProtocolError("invalid_params", "'candidate_ids' must be a list of strings when provided.")
        payload = archive_candidates_action(storage, candidate_ids=candidate_ids, reason=self._optional_string(params, "reason") or "Manual candidate archive.", reference_time=self._optional_string(params, "reference_time"))
        payload.update({"profile_id": storage.profile_id, "binding_source": source})
        return payload

    def _action_list_snapshots(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._optional_string(params, "scope")
        profile_id = self._optional_string(params, "profile_id")
        storage = self._profile_storage(profile_id) if profile_id else self._base_storage()
        return list_snapshots_payload(storage, scope=scope, profile_id=profile_id)

    def _action_restore_snapshot(self, params: dict[str, Any]) -> dict[str, Any]:
        storage = self._base_storage()
        return restore_snapshot_action(storage, snapshot_id=self._require_string(params, "snapshot_id"), profile_id=self._optional_string(params, "profile_id"))

    def _action_storage_health(self, params: dict[str, Any]) -> dict[str, Any]:
        profile_id = self._optional_string(params, "profile_id")
        storage = self._profile_storage(profile_id) if profile_id else self._base_storage()
        return storage_health_payload(storage, profile_id=profile_id)

    def _action_forget(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, source = self._resolve_storage_from_params(params)
        payload = forget_memory(storage, memory_id=self._require_string(params, "memory_id"), reason=self._optional_string(params, "reason") or "User requested memory removal.", hard_delete=self._optional_bool(params, "hard_delete", False))
        payload.update({"profile_id": storage.profile_id, "binding_source": source})
        return payload

    def _action_revise(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, source = self._resolve_storage_from_params(params)
        confidence = params.get("confidence")
        if confidence is not None and (not isinstance(confidence, (int, float)) or isinstance(confidence, bool)):
            raise RuntimeProtocolError("invalid_params", "'confidence' must be numeric.")
        payload = revise_memory(storage, memory_id=self._require_string(params, "memory_id"), summary=self._optional_string(params, "summary"), category=self._optional_string(params, "category"), confidence=float(confidence) if confidence is not None else None, mutable=self._optional_bool(params, "mutable", False), immutable=self._optional_bool(params, "immutable", False), activate=self._optional_bool(params, "activate", False), deactivate=self._optional_bool(params, "deactivate", False), superseded_by=self._optional_string(params, "superseded_by"), reason=self._optional_string(params, "reason") or "Manual memory correction.")
        payload.update({"profile_id": storage.profile_id, "binding_source": source})
        return payload

    def _action_replay_eval(self, params: dict[str, Any]) -> dict[str, Any]:
        from .evaluator import ReplayEvaluator

        manifest = self._require_string(params, "manifest")
        backend_name = self._optional_string(params, "backend") or DEFAULT_BACKEND
        output_dir = self._optional_string(params, "output_dir")
        return ReplayEvaluator(backend_name=backend_name).run(self._resolve_path(manifest), output_dir=Path(output_dir).resolve() if output_dir else None)

    def _action_export(self, params: dict[str, Any]) -> dict[str, Any]:
        storage, source = self._resolve_storage_from_params(params)
        all_profiles = self._optional_bool(params, "all_profiles", False)
        write_files = self._optional_bool(params, "write_files", False)
        output_dir_value = self._optional_string(params, "output_dir")
        export_json = export_payload(storage, all_profiles=all_profiles)
        markdown = build_export_markdown(export_json)
        payload: dict[str, Any] = {"profile_id": storage.profile_id, "binding_source": source, "payload": export_json, "markdown": markdown}
        if output_dir_value or write_files:
            output_dir = Path(output_dir_value).resolve() if output_dir_value else (storage.root / "exports")
            output_dir.mkdir(parents=True, exist_ok=True)
            json_path = output_dir / "personality-memory-export.json"
            markdown_path = output_dir / "personality-memory-export.md"
            write_json(json_path, export_json)
            markdown_path.write_text(markdown, encoding="utf-8")
            payload["json_path"] = str(json_path)
            payload["markdown_path"] = str(markdown_path)
        return payload

    def _persona_snapshot(self, persona: Any) -> dict[str, Any]:
        return {"generated_at": persona.generated_at, "memory_refs": list(persona.memory_refs), "markdown_summary": persona.markdown_summary}

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else (Path.cwd() / path).resolve()

    def _require_string(self, params: dict[str, Any], key: str) -> str:
        value = params.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeProtocolError("invalid_params", f"'{key}' is required and must be a non-empty string.")
        return value.strip()

    def _optional_string(self, params: dict[str, Any], key: str) -> str | None:
        value = params.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise RuntimeProtocolError("invalid_params", f"'{key}' must be a string when provided.")
        value = value.strip()
        return value or None

    def _optional_bool(self, params: dict[str, Any], key: str, default: bool) -> bool:
        value = params.get(key)
        if value is None:
            return default
        if not isinstance(value, bool):
            raise RuntimeProtocolError("invalid_params", f"'{key}' must be a boolean when provided.")
        return value

    def _optional_int(self, params: dict[str, Any], key: str, default: int) -> int:
        value = params.get(key)
        if value is None:
            return default
        if not isinstance(value, int) or isinstance(value, bool):
            raise RuntimeProtocolError("invalid_params", f"'{key}' must be an integer when provided.")
        return value

    def _map_exception(self, exc: Exception) -> RuntimeErrorPayload:
        if isinstance(exc, RuntimeProtocolError):
            return RuntimeErrorPayload(code=exc.code, message=exc.message, details=exc.details)
        if isinstance(exc, StorageBusyError):
            return RuntimeErrorPayload(code="storage_busy", message=str(exc))
        if isinstance(exc, SnapshotNotFoundError):
            return RuntimeErrorPayload(code="snapshot_not_found", message=str(exc))
        if isinstance(exc, StorageCorruptError):
            return RuntimeErrorPayload(code="storage_corrupt", message=str(exc))
        message = str(exc)
        lowered = message.lower()
        if message.startswith("Profile ") and "not found" in lowered:
            return RuntimeErrorPayload(code="profile_not_found", message=message)
        if message.startswith("Review item ") and "not found" in lowered:
            return RuntimeErrorPayload(code="review_not_found", message=message)
        if message.startswith("Candidate ") and "not found" in lowered:
            return RuntimeErrorPayload(code="candidate_not_found", message=message)
        if message.startswith("Memory ") and "not found" in lowered:
            return RuntimeErrorPayload(code="memory_not_found", message=message)
        if message.startswith("Session ") and "not found" in lowered:
            return RuntimeErrorPayload(code="session_not_found", message=message)
        if isinstance(exc, ValueError):
            return RuntimeErrorPayload(code="invalid_params", message=message)
        return RuntimeErrorPayload(code="internal_error", message="Internal runtime error.", details={"exception_type": type(exc).__name__, "message": message})
