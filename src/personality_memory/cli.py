from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .consolidator import MemoryConsolidator
from .evaluator import ReplayEvaluator
from .extractor import MemoryExtractor
from .governance import MemoryGovernanceManager
from .lifecycle import DEFAULT_AGING_POLICY, refresh_memory_activity
from .models import ConversationEvent, LongTermMemory, MemoryCandidate, ReviewItem, RevisionEntry
from .persona_builder import PersonaBuilder
from .retrieval import RetrievalService
from .storage import DEFAULT_BACKEND, SCHEMA_VERSION, Storage
from .utils import detect_project_root, normalize_timestamp, sentence_excerpt, sort_timestamp, stable_hash, utc_now, write_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persistent conversation memory and persona builder.")
    parser.add_argument("--root", type=Path, default=None, help="Skill/project root.")
    parser.add_argument("--profile", default=None, help="Profile id. Defaults to the registry default profile.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Ingest dialogue JSON.")
    ingest.add_argument("path", type=Path)
    ingest.set_defaults(func=cmd_ingest)

    extract = subparsers.add_parser("extract", help="Rebuild memory candidates.")
    extract.set_defaults(func=cmd_extract)

    consolidate = subparsers.add_parser("consolidate", help="Merge candidates into long-term memory.")
    consolidate.add_argument("--backend", choices=["lexical", "hybrid"], default=None)
    consolidate.set_defaults(func=cmd_consolidate)

    build_persona = subparsers.add_parser("build-persona", help="Generate persona profile.")
    build_persona.add_argument("--json", action="store_true")
    build_persona.set_defaults(func=cmd_build_persona)

    retrieve_context = subparsers.add_parser("retrieve-context", help="Return machine-readable runtime context.")
    retrieve_context.add_argument("--query", required=True)
    retrieve_context.add_argument("--top-k", type=int, default=5)
    retrieve_context.add_argument("--include-contested", action=argparse.BooleanOptionalAction, default=True)
    retrieve_context.add_argument("--include-review", action=argparse.BooleanOptionalAction, default=True)
    retrieve_context.add_argument("--backend", choices=["lexical", "hybrid"], default=None)
    retrieve_context.set_defaults(func=cmd_retrieve_context)

    prepare_context = subparsers.add_parser("prepare-context", help="Render assistant-ready Markdown context.")
    prepare_context.add_argument("--query", required=True)
    prepare_context.add_argument("--top-k", type=int, default=5)
    prepare_context.add_argument("--include-contested", action=argparse.BooleanOptionalAction, default=True)
    prepare_context.add_argument("--include-review", action=argparse.BooleanOptionalAction, default=True)
    prepare_context.add_argument("--backend", choices=["lexical", "hybrid"], default=None)
    prepare_context.set_defaults(func=cmd_prepare_context)

    show_memory = subparsers.add_parser("show-memory", help="Show long-term memory.")
    show_memory.add_argument("--json", action="store_true")
    show_memory.add_argument("--include-inactive", action="store_true")
    show_memory.set_defaults(func=cmd_show_memory)

    show_persona = subparsers.add_parser("show-persona", help="Show persona profile.")
    show_persona.add_argument("--json", action="store_true")
    show_persona.set_defaults(func=cmd_show_persona)

    forget = subparsers.add_parser("forget", help="Deactivate or delete a memory.")
    forget.add_argument("memory_id")
    forget.add_argument("--reason", default="User requested memory removal.")
    forget.add_argument("--hard-delete", action="store_true")
    forget.set_defaults(func=cmd_forget)

    revise = subparsers.add_parser("revise", help="Manually revise a memory.")
    revise.add_argument("memory_id")
    revise.add_argument("--summary")
    revise.add_argument("--category")
    revise.add_argument("--confidence", type=float)
    revise.add_argument("--mutable", action="store_true")
    revise.add_argument("--immutable", action="store_true")
    revise.add_argument("--activate", action="store_true")
    revise.add_argument("--deactivate", action="store_true")
    revise.add_argument("--superseded-by")
    revise.add_argument("--reason", default="Manual memory correction.")
    revise.set_defaults(func=cmd_revise)

    list_review = subparsers.add_parser("list-review", help="List review items.")
    list_review.add_argument("--status", choices=["open", "resolved", "dismissed"])
    list_review.add_argument("--json", action="store_true")
    list_review.set_defaults(func=cmd_list_review)

    show_review = subparsers.add_parser("show-review", help="Show a review item.")
    show_review.add_argument("review_id")
    show_review.add_argument("--json", action="store_true")
    show_review.set_defaults(func=cmd_show_review)

    resolve_review = subparsers.add_parser("resolve-review", help="Resolve a review item.")
    resolve_review.add_argument("review_id")
    resolve_review.add_argument("--action", required=True, choices=["accept-candidate", "merge-into", "replace-memory", "reject-candidate"])
    resolve_review.add_argument("--memory-id")
    resolve_review.add_argument("--reason", required=True)
    resolve_review.set_defaults(func=cmd_resolve_review)

    reopen_candidate = subparsers.add_parser("reopen-candidate", help="Reopen a candidate.")
    reopen_candidate.add_argument("candidate_id")
    reopen_candidate.add_argument("--reason", required=True)
    reopen_candidate.set_defaults(func=cmd_reopen_candidate)

    list_profiles = subparsers.add_parser("list-profiles", help="List profiles.")
    list_profiles.add_argument("--json", action="store_true")
    list_profiles.set_defaults(func=cmd_list_profiles)

    create_profile = subparsers.add_parser("create-profile", help="Create a profile.")
    create_profile.add_argument("profile_id")
    create_profile.add_argument("--display-name")
    create_profile.add_argument("--backend", choices=["lexical", "hybrid"], default=DEFAULT_BACKEND)
    create_profile.add_argument("--aging-policy", default=DEFAULT_AGING_POLICY)
    create_profile.add_argument("--set-default", action="store_true")
    create_profile.set_defaults(func=cmd_create_profile)

    show_profile = subparsers.add_parser("show-profile", help="Show profile metadata.")
    show_profile.add_argument("profile_id", nargs="?")
    show_profile.add_argument("--json", action="store_true")
    show_profile.set_defaults(func=cmd_show_profile)

    set_default_profile = subparsers.add_parser("set-default-profile", help="Set default profile.")
    set_default_profile.add_argument("profile_id")
    set_default_profile.set_defaults(func=cmd_set_default_profile)

    migrate_storage = subparsers.add_parser("migrate-storage", help="Ensure latest storage layout.")
    migrate_storage.add_argument("--json", action="store_true")
    migrate_storage.set_defaults(func=cmd_migrate_storage)

    replay_eval = subparsers.add_parser("replay-eval", help="Run replay evaluation.")
    replay_eval.add_argument("manifest", type=Path)
    replay_eval.add_argument("--output-dir", type=Path, default=None)
    replay_eval.add_argument("--backend", choices=["lexical", "hybrid"], default=None)
    replay_eval.set_defaults(func=cmd_replay_eval)

    export = subparsers.add_parser("export", help="Export memory state.")
    export.add_argument("--output-dir", type=Path, default=None)
    export.add_argument("--all-profiles", action="store_true")
    export.set_defaults(func=cmd_export)
    return parser


def resolve_root(root: Path | None) -> Path:
    return detect_project_root(root)


def open_storage(args: argparse.Namespace) -> Storage:
    return Storage(resolve_root(args.root), profile_id=args.profile)


def resolve_backend(storage: Storage, override: str | None) -> str:
    if override:
        return override
    profile = storage.get_profile_metadata()
    return profile.backend if profile is not None else DEFAULT_BACKEND


def cmd_ingest(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    existing_candidates = storage.load_memory_candidates()
    conversations = load_dialogue_payload(args.path)
    events = normalize_dialogue_payload(conversations)
    added_events = storage.append_conversation_events(events)
    extractor = MemoryExtractor()
    if not added_events:
        print("No new conversation events were added.")
        return 0

    id_index = {candidate.id: candidate for candidate in existing_candidates}
    extracted = extractor.extract_from_events(added_events, existing_candidates=existing_candidates)
    for candidate in extracted:
        id_index[candidate.id] = candidate
    combined = sorted(id_index.values(), key=lambda item: (sort_timestamp(item.created_at), item.id))
    storage.save_memory_candidates(combined)
    print(f"Ingested {len(added_events)} new conversation events from {args.path} into profile {storage.profile_id}.")
    print(f"Extracted {len(extracted)} candidate memories.")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    extractor = MemoryExtractor()
    candidates = extractor.extract_from_events(storage.load_conversation_events(), existing_candidates=storage.load_memory_candidates())
    storage.save_memory_candidates(candidates)
    print(f"Rebuilt {len(candidates)} candidate memories from {len(storage.load_conversation_events())} conversation events in profile {storage.profile_id}.")
    return 0


def cmd_consolidate(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    backend_name = resolve_backend(storage, args.backend)
    consolidator = MemoryConsolidator(backend_name=backend_name, aging_policy=storage.get_profile_metadata().aging_policy)
    result = consolidator.consolidate(storage.load_memory_candidates(), storage.load_long_term_memory(), storage.load_review_items())
    storage.save_memory_candidates(result.candidates)
    storage.save_long_term_memory(result.memories)
    storage.save_review_items(result.review_items)
    if result.revisions:
        storage.append_revisions(result.revisions)
    storage.touch_profile(storage.profile_id, backend=backend_name)
    print(f"Consolidation complete: profile={storage.profile_id}, created={result.created}, updated={result.updated}, conflicts={result.conflicts}, pending={result.pending}.")
    return 0


def cmd_build_persona(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    memories = storage.load_long_term_memory()
    profile = PersonaBuilder(aging_policy=storage.get_profile_metadata().aging_policy).build(memories)
    storage.save_long_term_memory(memories)
    storage.save_persona_profile(profile)
    print(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False) if args.json else profile.markdown_summary)
    return 0

def cmd_retrieve_context(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    memories = storage.load_long_term_memory()
    backend_name = resolve_backend(storage, args.backend)
    result = RetrievalService(backend_name=backend_name, aging_policy=storage.get_profile_metadata().aging_policy).retrieve(
        query=args.query,
        memories=memories,
        review_items=storage.load_review_items(),
        profile_id=storage.profile_id,
        top_k=max(0, args.top_k),
        include_contested=args.include_contested,
        include_review=args.include_review,
    )
    storage.save_long_term_memory(memories)
    storage.touch_profile(storage.profile_id, backend=backend_name)
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_prepare_context(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    memories = storage.load_long_term_memory()
    backend_name = resolve_backend(storage, args.backend)
    service = RetrievalService(backend_name=backend_name, aging_policy=storage.get_profile_metadata().aging_policy)
    result = service.retrieve(
        query=args.query,
        memories=memories,
        review_items=storage.load_review_items(),
        profile_id=storage.profile_id,
        top_k=max(0, args.top_k),
        include_contested=args.include_contested,
        include_review=args.include_review,
    )
    storage.save_long_term_memory(memories)
    storage.touch_profile(storage.profile_id, backend=backend_name)
    print(service.render_markdown(result, include_contested=args.include_contested, include_review=args.include_review))
    return 0


def cmd_show_memory(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    memories = storage.load_long_term_memory()
    if not args.include_inactive:
        memories = [memory for memory in memories if memory.active]
    if args.json:
        print(json.dumps([memory.to_dict() for memory in memories], indent=2, ensure_ascii=False))
        return 0
    if not memories:
        print("No long-term memory stored.")
        return 0
    for memory in sorted(memories, key=lambda item: (-item.confidence, item.category, item.id)):
        print(f"{memory.id} | {memory.category} | state={memory.lifecycle_state} | confidence={memory.confidence:.2f} | reinforced={memory.reinforcement_count} | contradictions={memory.contradiction_count}")
        print(f"  {memory.summary}")
        if memory.evidence:
            print(f"  evidence: {sentence_excerpt(memory.evidence[0].excerpt, 100)}")
    return 0


def cmd_show_persona(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    profile = storage.load_persona_profile()
    if profile is None:
        print("No persona profile built yet.")
        return 0
    print(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False) if args.json else profile.markdown_summary)
    return 0


def cmd_forget(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    memories = storage.load_long_term_memory()
    target = find_memory(memories, args.memory_id)
    if target is None:
        print(f"Memory {args.memory_id} not found.")
        return 1
    before = target.to_dict()
    if args.hard_delete:
        memories = [memory for memory in memories if memory.id != args.memory_id]
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
    storage.append_revisions([
        RevisionEntry(
            id=f"rev_{stable_hash(f'{action}|{args.memory_id}|{utc_now()}')}",
            entity_type="long_term_memory",
            entity_id=args.memory_id,
            action=action,
            timestamp=utc_now(),
            reason=args.reason,
            before=before,
            after=after,
        )
    ])
    print(f"Memory {args.memory_id} {'deleted' if args.hard_delete else 'deactivated' }.")
    return 0


def cmd_revise(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    memories = storage.load_long_term_memory()
    target = find_memory(memories, args.memory_id)
    if target is None:
        print(f"Memory {args.memory_id} not found.")
        return 1
    before = target.to_dict()
    if args.summary:
        target.summary = args.summary
    if args.category:
        target.category = args.category
    if args.confidence is not None:
        target.confidence = max(0.0, min(0.99, args.confidence))
    if args.mutable:
        target.mutable = True
    if args.immutable:
        target.mutable = False
    if args.superseded_by:
        target.superseded_by = args.superseded_by
    if args.deactivate:
        target.active = False
        target.lifecycle_state = "expired"
        target.staleness_score = 1.0
        target.stale_since = utc_now()
    else:
        if args.activate or args.summary or args.category or args.confidence is not None:
            refresh_memory_activity(target, reference_time=utc_now())
    storage.save_long_term_memory(memories)
    storage.append_revisions([
        RevisionEntry(
            id=f"rev_{stable_hash(f'revise|{args.memory_id}|{utc_now()}')}",
            entity_type="long_term_memory",
            entity_id=args.memory_id,
            action="revise",
            timestamp=utc_now(),
            reason=args.reason,
            before=before,
            after=target.to_dict(),
        )
    ])
    print(f"Revised memory {args.memory_id}.")
    return 0


def cmd_list_review(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    review_items = storage.load_review_items()
    if args.status:
        review_items = [item for item in review_items if item.status == args.status]
    review_items.sort(key=lambda item: (sort_timestamp(item.opened_at), item.id))
    if args.json:
        print(json.dumps([item.to_dict() for item in review_items], indent=2, ensure_ascii=False))
        return 0
    if not review_items:
        print("No review items found.")
        return 0
    for item in review_items:
        target = item.target_memory_id or "(new memory candidate)"
        print(f"{item.id} | status={item.status} | candidate={item.candidate_id} | target={target} | kind={item.kind}")
        print(f"  reason: {item.reason}")
    return 0


def cmd_show_review(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    review = find_review(storage.load_review_items(), args.review_id)
    if review is None:
        print(f"Review item {args.review_id} not found.")
        return 1
    if args.json:
        print(json.dumps(review.to_dict(), indent=2, ensure_ascii=False))
        return 0
    print(f"{review.id} | status={review.status} | kind={review.kind}")
    print(f"candidate: {review.candidate_id}")
    print(f"target_memory: {review.target_memory_id or '(new memory candidate)'}")
    print(f"reason: {review.reason}")
    if review.resolution_action:
        print(f"resolution: {review.resolution_action}")
    if review.resolution_notes:
        print(f"notes: {review.resolution_notes}")
    return 0


def cmd_resolve_review(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    result = MemoryGovernanceManager().resolve_review(
        review_id=args.review_id,
        action=args.action,
        reason=args.reason,
        candidates=storage.load_memory_candidates(),
        memories=storage.load_long_term_memory(),
        review_items=storage.load_review_items(),
        memory_id=args.memory_id,
    )
    storage.save_memory_candidates(result.candidates)
    storage.save_long_term_memory(result.memories)
    storage.save_review_items(result.review_items)
    if result.revisions:
        storage.append_revisions(result.revisions)
    print(f"Resolved review {args.review_id} with action {args.action}.")
    return 0


def cmd_reopen_candidate(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    result = MemoryGovernanceManager().reopen_candidate(
        candidate_id=args.candidate_id,
        reason=args.reason,
        candidates=storage.load_memory_candidates(),
        review_items=storage.load_review_items(),
        memories=storage.load_long_term_memory(),
    )
    storage.save_memory_candidates(result.candidates)
    storage.save_long_term_memory(result.memories)
    storage.save_review_items(result.review_items)
    if result.revisions:
        storage.append_revisions(result.revisions)
    print(f"Reopened candidate {args.candidate_id}.")
    return 0

def cmd_list_profiles(args: argparse.Namespace) -> int:
    storage = Storage(resolve_root(args.root), profile_id=args.profile)
    profiles = storage.list_profiles()
    if args.json:
        print(json.dumps([profile.to_dict() for profile in profiles], indent=2, ensure_ascii=False))
        return 0
    for profile in profiles:
        marker = "*" if profile.id == storage.registry.default_profile_id else " "
        print(f"{marker} {profile.id} | {profile.display_name} | backend={profile.backend} | aging={profile.aging_policy}")
    return 0


def cmd_create_profile(args: argparse.Namespace) -> int:
    storage = Storage(resolve_root(args.root), profile_id=args.profile)
    profile = storage.create_profile(
        args.profile_id,
        display_name=args.display_name,
        backend=args.backend,
        aging_policy=args.aging_policy,
    )
    if args.set_default:
        storage.set_default_profile(profile.id)
    print(f"Created profile {profile.id}.")
    return 0


def cmd_show_profile(args: argparse.Namespace) -> int:
    storage = Storage(resolve_root(args.root), profile_id=args.profile)
    profile = storage.get_profile_metadata(args.profile_id or storage.profile_id)
    if profile is None:
        print(f"Profile {args.profile_id} not found.")
        return 1
    payload = {"schema_version": storage.registry.schema_version, "default_profile_id": storage.registry.default_profile_id, "profile": profile.to_dict()}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    print(f"{profile.id} | display_name={profile.display_name}")
    print(f"backend: {profile.backend}")
    print(f"aging_policy: {profile.aging_policy}")
    print(f"created_at: {profile.created_at}")
    print(f"updated_at: {profile.updated_at}")
    return 0


def cmd_set_default_profile(args: argparse.Namespace) -> int:
    storage = Storage(resolve_root(args.root), profile_id=args.profile)
    profile = storage.set_default_profile(args.profile_id)
    print(f"Default profile set to {profile.id}.")
    return 0


def cmd_migrate_storage(args: argparse.Namespace) -> int:
    storage = Storage(resolve_root(args.root), profile_id=args.profile)
    payload = storage.migration_status()
    payload["migrations"] = [item.to_dict() for item in storage.load_migrations()]
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    print(f"Schema version: {payload['schema_version']}")
    print(f"Default profile: {payload['default_profile_id']}")
    print(f"Profiles: {', '.join(payload['profiles'])}")
    if payload["last_migration"]:
        print(f"Last migration: {payload['last_migration']['name']} @ {payload['last_migration']['applied_at']}")
    return 0


def cmd_replay_eval(args: argparse.Namespace) -> int:
    storage = Storage(resolve_root(args.root), profile_id=args.profile)
    backend_name = resolve_backend(storage, args.backend)
    report = ReplayEvaluator(backend_name=backend_name).run(args.manifest, output_dir=args.output_dir)
    print(f"Replay evaluation written to {report['json_path']}")
    print(f"Replay evaluation markdown written to {report['markdown_path']}")
    return 0 if report["passed"] else 1


def cmd_export(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    output_dir = args.output_dir or (storage.root / "exports")
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.all_profiles:
        export_json = {
            "schema_version": SCHEMA_VERSION,
            "registry": storage.registry.to_dict(),
            "migrations": [entry.to_dict() for entry in storage.load_migrations()],
            "profiles": storage.export_all_profiles_state(),
        }
    else:
        persona = storage.load_persona_profile()
        export_json = {
            "schema_version": SCHEMA_VERSION,
            "profile_id": storage.profile_id,
            "profile": storage.get_profile_metadata().to_dict(),
            "conversation_events": [event.to_dict() for event in storage.load_conversation_events()],
            "memory_candidates": [candidate.to_dict() for candidate in storage.load_memory_candidates()],
            "long_term_memory": [memory.to_dict() for memory in storage.load_long_term_memory()],
            "persona_profile": persona.to_dict() if persona else {},
            "review_items": [item.to_dict() for item in storage.load_review_items()],
            "revisions": [entry.to_dict() for entry in storage.load_revisions()],
        }
    json_path = output_dir / "personality-memory-export.json"
    markdown_path = output_dir / "personality-memory-export.md"
    write_json(json_path, export_json)
    markdown_path.write_text(build_export_markdown(export_json), encoding="utf-8")
    print(f"Exported JSON to {json_path}")
    print(f"Exported Markdown to {markdown_path}")
    return 0


def load_dialogue_payload(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_dialogue_payload(payload: Any) -> list[ConversationEvent]:
    conversations: list[dict[str, Any]]
    message_keys = {"speaker", "text", "message_id", "timestamp"}
    if isinstance(payload, dict) and "messages" in payload:
        conversations = [payload]
    elif isinstance(payload, list) and payload and all(isinstance(item, dict) and "messages" not in item and any(key in item for key in message_keys) for item in payload):
        conversations = [{"messages": payload}]
    elif isinstance(payload, list) and payload and all(isinstance(item, dict) and "messages" not in item for item in payload):
        raise ValueError("Top-level list items without 'messages' must look like message objects.")
    elif isinstance(payload, list):
        conversations = payload
    else:
        raise ValueError("Dialogue file must contain a conversation object, a message list, or a list of conversations.")

    events: list[ConversationEvent] = []
    for conversation_index, conversation in enumerate(conversations):
        if not isinstance(conversation, dict):
            raise ValueError(f"Conversation at index {conversation_index} must be an object with a 'messages' field.")
        messages = conversation.get("messages", [])
        if not isinstance(messages, list):
            raise ValueError(f"Conversation at index {conversation_index} has invalid 'messages'; expected a list.")
        session_id = conversation.get("session_id") or f"session_{conversation_index + 1}"
        for message_index, message in enumerate(messages):
            if not isinstance(message, dict):
                raise ValueError(f"Message at conversation index {conversation_index}, message index {message_index} must be an object.")
            message_id = str(message.get("message_id") or f"m{message_index + 1}")
            if "speaker" in message and not isinstance(message["speaker"], str):
                raise ValueError(f"Message at conversation index {conversation_index}, message index {message_index} has invalid 'speaker'; expected a string.")
            speaker = message.get("speaker", "user")
            raw_text = message.get("text", "")
            if "text" in message and not isinstance(raw_text, str):
                raise ValueError(f"Message at conversation index {conversation_index}, message index {message_index} has invalid 'text'; expected a string.")
            text = raw_text.strip()
            if not text:
                continue
            if "timestamp" in message and not isinstance(message["timestamp"], str):
                raise ValueError(f"Message at conversation index {conversation_index}, message index {message_index} has invalid 'timestamp'; expected a string.")
            try:
                occurred_at = normalize_timestamp(message["timestamp"]) if "timestamp" in message else utc_now()
            except ValueError as exc:
                raise ValueError(f"Message at conversation index {conversation_index}, message index {message_index} has invalid 'timestamp': {exc}") from exc
            normalized_session_id = str(session_id)
            event_id = f"evt_{stable_hash(f'{normalized_session_id}|{message_id}|{text}') }"
            events.append(ConversationEvent(id=event_id, session_id=normalized_session_id, message_id=message_id, speaker=speaker, text=text, occurred_at=occurred_at))
    return events


def find_memory(memories: list[LongTermMemory], memory_id: str) -> LongTermMemory | None:
    return next((memory for memory in memories if memory.id == memory_id), None)


def find_review(review_items: list[ReviewItem], review_id: str) -> ReviewItem | None:
    return next((item for item in review_items if item.id == review_id), None)


def build_export_markdown(payload: dict[str, Any]) -> str:
    if "profiles" in payload:
        lines = ["# Personality Memory Export", "", f"- Schema version: {payload['schema_version']}", f"- Profiles: {len(payload['profiles'])}", "", "## Profiles"]
        for profile_id, profile_payload in payload["profiles"].items():
            lines.append(f"- `{profile_id}` memories={len(profile_payload['long_term_memory'])} candidates={len(profile_payload['memory_candidates'])} reviews={len(profile_payload['review_items'])}")
        return "\n".join(lines)
    lines = ["# Personality Memory Export", "", f"- Schema version: {payload['schema_version']}", f"- Profile: {payload['profile_id']}", f"- Conversation events: {len(payload['conversation_events'])}", f"- Memory candidates: {len(payload['memory_candidates'])}", f"- Long-term memories: {len(payload['long_term_memory'])}", f"- Review items: {len(payload['review_items'])}", f"- Revisions: {len(payload['revisions'])}", "", "## Long-Term Memory"]
    if payload["long_term_memory"]:
        for memory in payload["long_term_memory"]:
            lines.append(f"- `{memory['id']}` [{memory['category']}] state={memory.get('lifecycle_state', 'active')} confidence={memory['confidence']}: {memory['summary']}")
    else:
        lines.append("- None")
    lines.extend(["", "## Review Items"])
    if payload["review_items"]:
        for item in payload["review_items"]:
            target = item["target_memory_id"] or "(new memory candidate)"
            lines.append(f"- `{item['id']}` status={item['status']} candidate={item['candidate_id']} target={target} kind={item['kind']}")
    else:
        lines.append("- None")
    lines.extend(["", "## Persona Profile"])
    persona = payload.get("persona_profile") or {}
    lines.append(persona.get("markdown_summary", "- No persona profile built."))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
