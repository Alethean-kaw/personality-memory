from __future__ import annotations

from pathlib import Path
from typing import Any

from .candidate_lifecycle import refresh_candidate_collections, restore_archived_candidate
from .consolidator import MemoryConsolidator
from .extractor import MemoryExtractor
from .governance import MemoryGovernanceManager
from .lifecycle import refresh_memory_activity
from .models import LongTermMemory, MemoryCandidate, PersonaProfile, RevisionEntry
from .persona_builder import PersonaBuilder
from .retrieval import RetrievalService
from .storage import DEFAULT_BACKEND, Storage
from .utils import latest_timestamp, sort_timestamp, stable_hash, utc_now


def resolve_backend(storage: Storage, override: str | None) -> str:
    if override:
        return override
    profile = storage.get_profile_metadata()
    return profile.backend if profile is not None else DEFAULT_BACKEND


def current_reference_time(storage: Storage) -> str:
    timestamps = [event.occurred_at for event in storage.load_conversation_events() if event.occurred_at]
    timestamps.extend(candidate.last_seen or candidate.created_at for candidate in storage.load_memory_candidates() if (candidate.last_seen or candidate.created_at))
    timestamps.extend(candidate.archived_at or candidate.last_seen or candidate.created_at for candidate in storage.load_candidate_archive() if (candidate.archived_at or candidate.last_seen or candidate.created_at))
    timestamps.extend(memory.last_reinforced_at or memory.last_seen or memory.first_seen for memory in storage.load_long_term_memory() if (memory.last_reinforced_at or memory.last_seen or memory.first_seen))
    persona = storage.load_persona_profile()
    if persona is not None and persona.generated_at:
        timestamps.append(persona.generated_at)
    return latest_timestamp(*timestamps) or utc_now()


def refresh_candidate_workspace(storage: Storage, *, reference_time: str | None = None) -> Any:
    refresh = refresh_candidate_collections(storage.load_memory_candidates(), storage.load_candidate_archive(), reference_time=reference_time or current_reference_time(storage))
    storage.save_memory_candidates(refresh.active_candidates)
    storage.save_candidate_archive(refresh.archived_candidates)
    return refresh


def find_memory(memories: list[LongTermMemory], memory_id: str) -> LongTermMemory | None:
    return next((memory for memory in memories if memory.id == memory_id), None)


def find_candidate(candidates: list[MemoryCandidate], candidate_id: str) -> MemoryCandidate | None:
    return next((candidate for candidate in candidates if candidate.id == candidate_id), None)


def ingest_payload(storage: Storage, payload: Any, *, events: list[Any]) -> dict[str, Any]:
    extractor = MemoryExtractor()
    with storage.mutation("ingest", scope="profile", profile_id=storage.profile_id):
        added_events = storage.append_conversation_events(events)
        active = storage.load_memory_candidates()
        archived = storage.load_candidate_archive()
        extracted = extractor.extract_from_events(added_events, existing_candidates=active, archived_candidates=archived) if added_events else []
        id_index = {candidate.id: candidate for candidate in active}
        for candidate in extracted:
            id_index[candidate.id] = candidate
        reference = current_reference_time(storage)
        refresh = refresh_candidate_collections(sorted(id_index.values(), key=lambda item: (sort_timestamp(item.created_at), item.id)), archived, reference_time=reference)
        storage.save_memory_candidates(refresh.active_candidates)
        storage.save_candidate_archive(refresh.archived_candidates)
    return {"events_added": len(added_events), "candidates_extracted": len(extracted), "candidate_total": len(refresh.active_candidates), "candidates_archived": refresh.archived_count}


def extract_candidates(storage: Storage) -> dict[str, Any]:
    extractor = MemoryExtractor()
    with storage.mutation("extract", scope="profile", profile_id=storage.profile_id):
        events = storage.load_conversation_events()
        archived = storage.load_candidate_archive()
        candidates = extractor.extract_from_events(events, existing_candidates=storage.load_memory_candidates(), archived_candidates=archived)
        refresh = refresh_candidate_collections(candidates, archived, reference_time=current_reference_time(storage))
        storage.save_memory_candidates(refresh.active_candidates)
        storage.save_candidate_archive(refresh.archived_candidates)
    return {"conversation_event_count": len(events), "candidate_count": len(refresh.active_candidates), "candidates_archived": refresh.archived_count}


def consolidate_profile(storage: Storage, *, backend_override: str | None = None) -> dict[str, Any]:
    with storage.mutation("consolidate", scope="profile", profile_id=storage.profile_id):
        reference = current_reference_time(storage)
        refresh = refresh_candidate_workspace(storage, reference_time=reference)
        backend_name = resolve_backend(storage, backend_override)
        profile = storage.get_profile_metadata()
        result = MemoryConsolidator(backend_name=backend_name, aging_policy=profile.aging_policy).consolidate(storage.load_memory_candidates(), storage.load_long_term_memory(), storage.load_review_items(), reference_time=reference)
        result.candidates_archived = refresh.archived_count
        storage.save_memory_candidates(result.candidates)
        storage.save_candidate_archive(storage.load_candidate_archive())
        storage.save_long_term_memory(result.memories)
        storage.save_review_items(result.review_items)
        if result.revisions:
            storage.append_revisions(result.revisions)
        storage.touch_profile(storage.profile_id, backend=backend_name)
    return {"backend": backend_name, "result": result}


def build_persona_profile(storage: Storage) -> PersonaProfile:
    with storage.mutation("build-persona", scope="profile", profile_id=storage.profile_id):
        refresh_candidate_workspace(storage)
        memories = storage.load_long_term_memory()
        persona = PersonaBuilder(aging_policy=storage.get_profile_metadata().aging_policy).build(memories, reference_time=current_reference_time(storage))
        storage.save_long_term_memory(memories)
        storage.save_persona_profile(persona)
    return persona


def retrieve_context_bundle(storage: Storage, *, query: str, top_k: int = 5, include_contested: bool = True, include_review: bool = True, backend_override: str | None = None):
    with storage.mutation("retrieve-context", scope="profile", profile_id=storage.profile_id):
        refresh_candidate_workspace(storage)
        memories = storage.load_long_term_memory()
        backend_name = resolve_backend(storage, backend_override)
        result = RetrievalService(backend_name=backend_name, aging_policy=storage.get_profile_metadata().aging_policy).retrieve(query=query, memories=memories, review_items=storage.load_review_items(), profile_id=storage.profile_id, top_k=max(0, top_k), include_contested=include_contested, include_review=include_review, reference_time=current_reference_time(storage))
        storage.save_long_term_memory(memories)
        storage.touch_profile(storage.profile_id, backend=backend_name)
    return result


def prepare_context_bundle(storage: Storage, *, query: str, top_k: int = 5, include_contested: bool = True, include_review: bool = True, backend_override: str | None = None) -> tuple[Any, str]:
    with storage.mutation("prepare-context", scope="profile", profile_id=storage.profile_id):
        refresh_candidate_workspace(storage)
        memories = storage.load_long_term_memory()
        backend_name = resolve_backend(storage, backend_override)
        service = RetrievalService(backend_name=backend_name, aging_policy=storage.get_profile_metadata().aging_policy)
        result = service.retrieve(query=query, memories=memories, review_items=storage.load_review_items(), profile_id=storage.profile_id, top_k=max(0, top_k), include_contested=include_contested, include_review=include_review, reference_time=current_reference_time(storage))
        storage.save_long_term_memory(memories)
        storage.touch_profile(storage.profile_id, backend=backend_name)
    return result, service.render_markdown(result, include_contested=include_contested, include_review=include_review)


def forget_memory(storage: Storage, *, memory_id: str, reason: str, hard_delete: bool) -> dict[str, Any]:
    with storage.mutation("forget", scope="profile", profile_id=storage.profile_id):
        memories = storage.load_long_term_memory()
        target = find_memory(memories, memory_id)
        if target is None:
            raise ValueError(f"Memory {memory_id} not found.")
        before = target.to_dict()
        if hard_delete:
            memories = [memory for memory in memories if memory.id != memory_id]
            action = "hard_delete"
            after = None
        else:
            target.active = False
            target.lifecycle_state = "expired"
            target.staleness_score = 1.0
            target.stale_since = utc_now()
            action = "forget"
            after = target.to_dict()
        storage.save_long_term_memory(memories)
        revision = RevisionEntry(id=f"rev_{stable_hash(f'{action}|{memory_id}|{utc_now()}')}", entity_type="long_term_memory", entity_id=memory_id, action=action, timestamp=utc_now(), reason=reason, before=before, after=after)
        storage.append_revisions([revision])
    return {"memory_id": memory_id, "action": action, "revision_id": revision.id}


def revise_memory(storage: Storage, *, memory_id: str, summary: str | None, category: str | None, confidence: float | None, mutable: bool, immutable: bool, activate: bool, deactivate: bool, superseded_by: str | None, reason: str) -> dict[str, Any]:
    with storage.mutation("revise", scope="profile", profile_id=storage.profile_id):
        memories = storage.load_long_term_memory()
        target = find_memory(memories, memory_id)
        if target is None:
            raise ValueError(f"Memory {memory_id} not found.")
        before = target.to_dict()
        if summary:
            target.summary = summary
        if category:
            target.category = category
        if confidence is not None:
            target.confidence = max(0.0, min(0.99, confidence))
        if mutable:
            target.mutable = True
        if immutable:
            target.mutable = False
        if superseded_by:
            target.superseded_by = superseded_by
        if deactivate:
            target.active = False
            target.lifecycle_state = "expired"
            target.staleness_score = 1.0
            target.stale_since = utc_now()
        elif activate or summary or category or confidence is not None:
            refresh_memory_activity(target, reference_time=utc_now())
        storage.save_long_term_memory(memories)
        revision = RevisionEntry(id=f"rev_{stable_hash(f'revise|{memory_id}|{utc_now()}')}", entity_type="long_term_memory", entity_id=memory_id, action="revise", timestamp=utc_now(), reason=reason, before=before, after=target.to_dict())
        storage.append_revisions([revision])
    return {"memory_id": memory_id, "memory": target.to_dict(), "revision_id": revision.id}


def resolve_review_action(storage: Storage, *, review_id: str, action: str, reason: str, memory_id: str | None = None) -> dict[str, Any]:
    with storage.mutation("resolve-review", scope="profile", profile_id=storage.profile_id):
        archived = storage.load_candidate_archive()
        result = MemoryGovernanceManager().resolve_review(review_id=review_id, action=action, reason=reason, candidates=storage.load_memory_candidates(), archived_candidates=archived, memories=storage.load_long_term_memory(), review_items=storage.load_review_items(), memory_id=memory_id)
        storage.save_memory_candidates(result.candidates)
        storage.save_candidate_archive(result.archived_candidates)
        storage.save_long_term_memory(result.memories)
        storage.save_review_items(result.review_items)
        if result.revisions:
            storage.append_revisions(result.revisions)
    return {"review_id": review_id, "action": action, "revision_ids": [revision.id for revision in result.revisions]}


def reopen_candidate_action(storage: Storage, *, candidate_id: str, reason: str) -> dict[str, Any]:
    with storage.mutation("reopen-candidate", scope="profile", profile_id=storage.profile_id):
        result = MemoryGovernanceManager().reopen_candidate(candidate_id=candidate_id, reason=reason, candidates=storage.load_memory_candidates(), archived_candidates=storage.load_candidate_archive(), review_items=storage.load_review_items(), memories=storage.load_long_term_memory())
        storage.save_memory_candidates(result.candidates)
        storage.save_candidate_archive(result.archived_candidates)
        storage.save_long_term_memory(result.memories)
        storage.save_review_items(result.review_items)
        if result.revisions:
            storage.append_revisions(result.revisions)
    return {"candidate_id": candidate_id, "revision_ids": [revision.id for revision in result.revisions]}


def list_candidates_payload(storage: Storage, *, include_archived: bool, status: str | None = None, lifecycle_state: str | None = None) -> dict[str, Any]:
    active = storage.load_memory_candidates()
    archived = storage.load_candidate_archive() if include_archived else []
    rows = [("active", item) for item in active] + [("archived", item) for item in archived]
    if status:
        rows = [row for row in rows if row[1].status == status]
    if lifecycle_state:
        rows = [row for row in rows if row[1].lifecycle_state == lifecycle_state]
    rows.sort(key=lambda row: (sort_timestamp(row[1].created_at), row[1].id))
    return {"active_candidates": [item.to_dict() | {"candidate_store": store} for store, item in rows if store == "active"], "archived_candidates": [item.to_dict() | {"candidate_store": store} for store, item in rows if store == "archived"]}


def show_candidate_payload(storage: Storage, *, candidate_id: str) -> dict[str, Any]:
    candidate = find_candidate(storage.load_memory_candidates(), candidate_id)
    if candidate is not None:
        return {"candidate": candidate.to_dict() | {"candidate_store": "active"}}
    candidate = find_candidate(storage.load_candidate_archive(), candidate_id)
    if candidate is not None:
        return {"candidate": candidate.to_dict() | {"candidate_store": "archived"}}
    raise ValueError(f"Candidate {candidate_id} not found.")


def restore_candidate_action(storage: Storage, *, candidate_id: str, reason: str) -> dict[str, Any]:
    with storage.mutation("restore-candidate", scope="profile", profile_id=storage.profile_id):
        refresh = restore_archived_candidate(candidate_id, candidates=storage.load_memory_candidates(), archived_candidates=storage.load_candidate_archive(), reason=reason)
        storage.save_memory_candidates(refresh.active_candidates)
        storage.save_candidate_archive(refresh.archived_candidates)
        revision = RevisionEntry(id=f"rev_{stable_hash(f'restore-candidate|{candidate_id}|{utc_now()}')}", entity_type="memory_candidate", entity_id=candidate_id, action="restore_candidate", timestamp=utc_now(), reason=reason, before={"candidate_store": "archived"}, after={"candidate_store": "active"})
        storage.append_revisions([revision])
    return {"candidate_id": candidate_id, "restored": refresh.restored_count, "revision_id": revision.id}


def archive_candidates_action(storage: Storage, *, candidate_ids: list[str], reason: str, reference_time: str | None = None) -> dict[str, Any]:
    with storage.mutation("archive-candidates", scope="profile", profile_id=storage.profile_id):
        active = storage.load_memory_candidates()
        archived = storage.load_candidate_archive()
        forced = 0
        skipped: list[str] = []
        if candidate_ids:
            remaining: list[MemoryCandidate] = []
            for candidate in active:
                if candidate.id not in candidate_ids:
                    remaining.append(candidate)
                    continue
                if candidate.status == "review":
                    skipped.append(candidate.id)
                    remaining.append(candidate)
                    continue
                candidate.lifecycle_state = "archived"
                candidate.archived_at = reference_time or utc_now()
                candidate.archive_reason = reason
                if candidate.status == "candidate":
                    candidate.status = "outdated"
                archived.append(candidate)
                forced += 1
            refresh = refresh_candidate_collections(remaining, archived, reference_time=reference_time or current_reference_time(storage))
        else:
            refresh = refresh_candidate_collections(active, archived, reference_time=reference_time or current_reference_time(storage))
        storage.save_memory_candidates(refresh.active_candidates)
        storage.save_candidate_archive(refresh.archived_candidates)
    return {"archived": refresh.archived_count + forced, "restored": refresh.restored_count, "skipped_candidate_ids": skipped}


def export_payload(storage: Storage, *, all_profiles: bool) -> dict[str, Any]:
    if all_profiles:
        return {"schema_version": storage.registry.schema_version, "registry": storage.registry.to_dict(), "migrations": [entry.to_dict() for entry in storage.load_migrations()], "profiles": storage.export_all_profiles_state()}
    persona = storage.load_persona_profile()
    return {"schema_version": storage.registry.schema_version, "profile_id": storage.profile_id, "profile": storage.get_profile_metadata().to_dict(), "conversation_events": [event.to_dict() for event in storage.load_conversation_events()], "memory_candidates": [candidate.to_dict() for candidate in storage.load_memory_candidates()], "candidate_archive": [candidate.to_dict() for candidate in storage.load_candidate_archive()], "long_term_memory": [memory.to_dict() for memory in storage.load_long_term_memory()], "persona_profile": persona.to_dict() if persona else {}, "review_items": [item.to_dict() for item in storage.load_review_items()], "revisions": [entry.to_dict() for entry in storage.load_revisions()]}


def list_snapshots_payload(storage: Storage, *, scope: str | None = None, profile_id: str | None = None) -> dict[str, Any]:
    return {"snapshots": storage.list_snapshots(scope=scope, profile_id=profile_id or storage.profile_id if scope == "profile" else profile_id)}


def restore_snapshot_action(storage: Storage, *, snapshot_id: str, profile_id: str | None = None) -> dict[str, Any]:
    scope = "profile" if profile_id or snapshot_id not in {item["id"] for item in storage.list_snapshots(scope="global")} else "global"
    with storage.mutation("restore-snapshot", scope=scope, profile_id=profile_id or storage.profile_id):
        return storage.restore_snapshot(snapshot_id, profile_id=profile_id)


def storage_health_payload(storage: Storage, *, profile_id: str | None = None) -> dict[str, Any]:
    return storage.storage_health(profile_id=profile_id or storage.profile_id)
