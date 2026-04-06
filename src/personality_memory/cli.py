from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .models import ConversationEvent, LongTermMemory, ReviewItem
from .operations import (
    archive_candidates_action,
    build_persona_profile,
    consolidate_profile,
    export_payload,
    extract_candidates,
    find_memory,
    forget_memory,
    ingest_payload,
    list_candidates_payload,
    list_snapshots_payload,
    prepare_context_bundle,
    reopen_candidate_action,
    resolve_review_action,
    restore_candidate_action,
    restore_snapshot_action,
    retrieve_context_bundle,
    revise_memory,
    show_candidate_payload,
    storage_health_payload,
)
from .storage import DEFAULT_BACKEND, SCHEMA_VERSION, Storage
from .utils import detect_project_root, normalize_timestamp, sentence_excerpt, stable_hash, utc_now, write_json


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

    list_candidates = subparsers.add_parser("list-candidates", help="List active and archived candidates.")
    list_candidates.add_argument("--json", action="store_true")
    list_candidates.add_argument("--include-archived", action="store_true")
    list_candidates.add_argument("--status", choices=["candidate", "accepted", "review", "rejected", "outdated"])
    list_candidates.add_argument("--lifecycle-state", choices=["active", "cooling", "archived"])
    list_candidates.set_defaults(func=cmd_list_candidates)

    show_candidate = subparsers.add_parser("show-candidate", help="Show a candidate from active or archive storage.")
    show_candidate.add_argument("candidate_id")
    show_candidate.add_argument("--json", action="store_true")
    show_candidate.set_defaults(func=cmd_show_candidate)

    restore_candidate = subparsers.add_parser("restore-candidate", help="Restore an archived candidate back into the active working set.")
    restore_candidate.add_argument("candidate_id")
    restore_candidate.add_argument("--reason", required=True)
    restore_candidate.set_defaults(func=cmd_restore_candidate)

    archive_candidates = subparsers.add_parser("archive-candidates", help="Archive candidates by rule or explicit id.")
    archive_candidates.add_argument("candidate_ids", nargs="*")
    archive_candidates.add_argument("--reason", default="Manual candidate archive.")
    archive_candidates.add_argument("--reference-time")
    archive_candidates.set_defaults(func=cmd_archive_candidates)

    list_profiles = subparsers.add_parser("list-profiles", help="List profiles.")
    list_profiles.add_argument("--json", action="store_true")
    list_profiles.set_defaults(func=cmd_list_profiles)

    create_profile = subparsers.add_parser("create-profile", help="Create a profile.")
    create_profile.add_argument("profile_id")
    create_profile.add_argument("--display-name")
    create_profile.add_argument("--backend", choices=["lexical", "hybrid"], default=DEFAULT_BACKEND)
    create_profile.add_argument("--aging-policy", default="default-v1")
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

    list_snapshots = subparsers.add_parser("list-snapshots", help="List storage snapshots.")
    list_snapshots.add_argument("--scope", choices=["global", "profile"])
    list_snapshots.add_argument("--json", action="store_true")
    list_snapshots.set_defaults(func=cmd_list_snapshots)

    restore_snapshot = subparsers.add_parser("restore-snapshot", help="Restore a storage snapshot.")
    restore_snapshot.add_argument("snapshot_id")
    restore_snapshot.add_argument("--snapshot-profile")
    restore_snapshot.add_argument("--json", action="store_true")
    restore_snapshot.set_defaults(func=cmd_restore_snapshot)

    storage_health = subparsers.add_parser("storage-health", help="Run storage integrity checks.")
    storage_health.add_argument("--json", action="store_true")
    storage_health.set_defaults(func=cmd_storage_health)

    replay_eval = subparsers.add_parser("replay-eval", help="Run replay evaluation.")
    replay_eval.add_argument("manifest", type=Path)
    replay_eval.add_argument("--output-dir", type=Path, default=None)
    replay_eval.add_argument("--backend", choices=["lexical", "hybrid"], default=None)
    replay_eval.set_defaults(func=cmd_replay_eval)

    export = subparsers.add_parser("export", help="Export memory state.")
    export.add_argument("--output-dir", type=Path, default=None)
    export.add_argument("--all-profiles", action="store_true")
    export.set_defaults(func=cmd_export)

    session_runtime = subparsers.add_parser("session-runtime", help="Run the JSONL session runtime.")
    session_runtime.set_defaults(func=cmd_session_runtime)
    return parser


def resolve_root(root: Path | None) -> Path:
    return detect_project_root(root)


def open_storage(args: argparse.Namespace) -> Storage:
    return Storage(resolve_root(args.root), profile_id=args.profile)


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


def find_review(review_items: list[ReviewItem], review_id: str) -> ReviewItem | None:
    return next((item for item in review_items if item.id == review_id), None)


def cmd_ingest(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    result = ingest_payload(storage, load_dialogue_payload(args.path), events=normalize_dialogue_payload(load_dialogue_payload(args.path)))
    print(f"Ingested {result['events_added']} new conversation events from {args.path} into profile {storage.profile_id}.")
    print(f"Extracted {result['candidates_extracted']} candidate memories.")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    result = extract_candidates(storage)
    print(f"Rebuilt {result['candidate_count']} candidate memories from {result['conversation_event_count']} conversation events in profile {storage.profile_id}.")
    return 0


def cmd_consolidate(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    payload = consolidate_profile(storage, backend_override=args.backend)
    result = payload["result"]
    print(f"Consolidation complete: profile={storage.profile_id}, created={result.created}, updated={result.updated}, conflicts={result.conflicts}, pending={result.pending}, archived={result.candidates_archived}.")
    return 0


def cmd_build_persona(args: argparse.Namespace) -> int:
    persona = build_persona_profile(open_storage(args))
    print(json.dumps(persona.to_dict(), indent=2, ensure_ascii=False) if args.json else persona.markdown_summary)
    return 0


def cmd_retrieve_context(args: argparse.Namespace) -> int:
    result = retrieve_context_bundle(open_storage(args), query=args.query, top_k=args.top_k, include_contested=args.include_contested, include_review=args.include_review, backend_override=args.backend)
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_prepare_context(args: argparse.Namespace) -> int:
    _, markdown = prepare_context_bundle(open_storage(args), query=args.query, top_k=args.top_k, include_contested=args.include_contested, include_review=args.include_review, backend_override=args.backend)
    print(markdown)
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
    profile = open_storage(args).load_persona_profile()
    if profile is None:
        print("No persona profile built yet.")
        return 0
    print(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False) if args.json else profile.markdown_summary)
    return 0


def cmd_forget(args: argparse.Namespace) -> int:
    result = forget_memory(open_storage(args), memory_id=args.memory_id, reason=args.reason, hard_delete=args.hard_delete)
    print(f"Memory {result['memory_id']} {'deleted' if result['action'] == 'hard_delete' else 'deactivated' }.")
    return 0


def cmd_revise(args: argparse.Namespace) -> int:
    revise_memory(open_storage(args), memory_id=args.memory_id, summary=args.summary, category=args.category, confidence=args.confidence, mutable=args.mutable, immutable=args.immutable, activate=args.activate, deactivate=args.deactivate, superseded_by=args.superseded_by, reason=args.reason)
    print(f"Revised memory {args.memory_id}.")
    return 0


def cmd_list_review(args: argparse.Namespace) -> int:
    items = open_storage(args).load_review_items()
    if args.status:
        items = [item for item in items if item.status == args.status]
    items.sort(key=lambda item: (item.opened_at, item.id))
    if args.json:
        print(json.dumps([item.to_dict() for item in items], indent=2, ensure_ascii=False))
        return 0
    if not items:
        print("No review items found.")
        return 0
    for item in items:
        target = item.target_memory_id or "(new memory candidate)"
        print(f"{item.id} | status={item.status} | candidate={item.candidate_id} | target={target} | kind={item.kind}")
        print(f"  reason: {item.reason}")
    return 0


def cmd_show_review(args: argparse.Namespace) -> int:
    review = find_review(open_storage(args).load_review_items(), args.review_id)
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
    resolve_review_action(open_storage(args), review_id=args.review_id, action=args.action, reason=args.reason, memory_id=args.memory_id)
    print(f"Resolved review {args.review_id} with action {args.action}.")
    return 0


def cmd_reopen_candidate(args: argparse.Namespace) -> int:
    reopen_candidate_action(open_storage(args), candidate_id=args.candidate_id, reason=args.reason)
    print(f"Reopened candidate {args.candidate_id}.")
    return 0


def cmd_list_candidates(args: argparse.Namespace) -> int:
    payload = list_candidates_payload(open_storage(args), include_archived=args.include_archived, status=args.status, lifecycle_state=args.lifecycle_state)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    rows = [("active", item) for item in payload["active_candidates"]] + [("archived", item) for item in payload["archived_candidates"]]
    if not rows:
        print("No candidates found.")
        return 0
    for store, item in rows:
        print(f"{item['id']} | store={store} | status={item['status']} | lifecycle={item['lifecycle_state']} | confidence={item['confidence']:.2f}")
        print(f"  {item['content']}")
    return 0


def cmd_show_candidate(args: argparse.Namespace) -> int:
    payload = show_candidate_payload(open_storage(args), candidate_id=args.candidate_id)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    item = payload["candidate"]
    print(f"{item['id']} | store={item['candidate_store']} | status={item['status']} | lifecycle={item['lifecycle_state']}")
    print(f"content: {item['content']}")
    return 0


def cmd_restore_candidate(args: argparse.Namespace) -> int:
    restore_candidate_action(open_storage(args), candidate_id=args.candidate_id, reason=args.reason)
    print(f"Restored candidate {args.candidate_id}.")
    return 0


def cmd_archive_candidates(args: argparse.Namespace) -> int:
    result = archive_candidates_action(open_storage(args), candidate_ids=list(args.candidate_ids), reason=args.reason, reference_time=args.reference_time)
    print(f"Archived {result['archived']} candidates.")
    if result["skipped_candidate_ids"]:
        print(f"Skipped review candidates: {', '.join(result['skipped_candidate_ids'])}")
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
    profile = storage.create_profile(args.profile_id, display_name=args.display_name, backend=args.backend, aging_policy=args.aging_policy)
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
    profile = Storage(resolve_root(args.root), profile_id=args.profile).set_default_profile(args.profile_id)
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


def cmd_list_snapshots(args: argparse.Namespace) -> int:
    payload = list_snapshots_payload(open_storage(args), scope=args.scope, profile_id=args.profile if args.scope == 'profile' else None)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if not payload["snapshots"]:
        print("No snapshots found.")
        return 0
    for item in payload["snapshots"]:
        target = item.get("profile_id") or "global"
        print(f"{item['id']} | scope={item['scope']} | target={target} | action={item['action']}")
    return 0


def cmd_restore_snapshot(args: argparse.Namespace) -> int:
    payload = restore_snapshot_action(open_storage(args), snapshot_id=args.snapshot_id, profile_id=args.snapshot_profile)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    print(f"Restored snapshot {payload['snapshot_id']} ({payload['scope']}).")
    return 0


def cmd_storage_health(args: argparse.Namespace) -> int:
    payload = storage_health_payload(open_storage(args), profile_id=args.profile)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    print(f"Storage healthy: {payload['ok']}")
    for check in payload["checks"]:
        print(f"- {check['name']}: {check['passed']}")
    return 0 if payload["ok"] else 1


def cmd_replay_eval(args: argparse.Namespace) -> int:
    from .evaluator import ReplayEvaluator

    storage = Storage(resolve_root(args.root), profile_id=args.profile)
    report = ReplayEvaluator(backend_name=args.backend or storage.get_profile_metadata().backend).run(args.manifest, output_dir=args.output_dir)
    print(f"Replay evaluation written to {report['json_path']}")
    print(f"Replay evaluation markdown written to {report['markdown_path']}")
    return 0 if report["passed"] else 1


def cmd_export(args: argparse.Namespace) -> int:
    storage = open_storage(args)
    output_dir = args.output_dir or (storage.root / "exports")
    output_dir.mkdir(parents=True, exist_ok=True)
    export_json = export_payload(storage, all_profiles=args.all_profiles)
    json_path = output_dir / "personality-memory-export.json"
    markdown_path = output_dir / "personality-memory-export.md"
    write_json(json_path, export_json)
    markdown_path.write_text(build_export_markdown(export_json), encoding="utf-8")
    print(f"Exported JSON to {json_path}")
    print(f"Exported Markdown to {markdown_path}")
    return 0


def build_export_markdown(payload: dict[str, Any]) -> str:
    if "profiles" in payload:
        lines = ["# Personality Memory Export", "", f"- Schema version: {payload['schema_version']}", f"- Profiles: {len(payload['profiles'])}", "", "## Profiles"]
        for profile_id, profile_payload in payload["profiles"].items():
            lines.append(f"- `{profile_id}` memories={len(profile_payload['long_term_memory'])} candidates={len(profile_payload['memory_candidates'])} archived_candidates={len(profile_payload.get('candidate_archive', []))} reviews={len(profile_payload['review_items'])}")
        return "\n".join(lines)
    lines = ["# Personality Memory Export", "", f"- Schema version: {payload['schema_version']}", f"- Profile: {payload['profile_id']}", f"- Conversation events: {len(payload['conversation_events'])}", f"- Memory candidates: {len(payload['memory_candidates'])}", f"- Archived candidates: {len(payload.get('candidate_archive', []))}", f"- Long-term memories: {len(payload['long_term_memory'])}", f"- Review items: {len(payload['review_items'])}", f"- Revisions: {len(payload['revisions'])}", "", "## Long-Term Memory"]
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


def cmd_session_runtime(args: argparse.Namespace) -> int:
    from .runtime import SessionRuntime

    return SessionRuntime(resolve_root(args.root)).serve()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
