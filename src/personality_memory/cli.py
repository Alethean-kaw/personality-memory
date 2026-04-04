from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .consolidator import MemoryConsolidator
from .extractor import MemoryExtractor
from .models import ConversationEvent, LongTermMemory, RevisionEntry
from .persona_builder import PersonaBuilder
from .storage import Storage
from .utils import detect_project_root, sentence_excerpt, stable_hash, utc_now, write_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persistent conversation memory and persona builder.")
    parser.add_argument("--root", type=Path, default=None, help="Skill/project root. Defaults to auto-detection.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Ingest dialogue JSON and immediately extract memory candidates.")
    ingest.add_argument("path", type=Path, help="Path to a dialogue JSON file.")
    ingest.set_defaults(func=cmd_ingest)

    extract = subparsers.add_parser("extract", help="Rebuild memory candidates from stored conversation events.")
    extract.set_defaults(func=cmd_extract)

    consolidate = subparsers.add_parser("consolidate", help="Merge candidates into long-term memory.")
    consolidate.set_defaults(func=cmd_consolidate)

    build_persona = subparsers.add_parser("build-persona", help="Generate the persona profile from long-term memory.")
    build_persona.add_argument("--json", action="store_true", help="Print JSON instead of Markdown.")
    build_persona.set_defaults(func=cmd_build_persona)

    show_memory = subparsers.add_parser("show-memory", help="Display current long-term memory.")
    show_memory.add_argument("--json", action="store_true", help="Print JSON.")
    show_memory.add_argument("--include-inactive", action="store_true", help="Include inactive memories.")
    show_memory.set_defaults(func=cmd_show_memory)

    show_persona = subparsers.add_parser("show-persona", help="Display the current persona profile.")
    show_persona.add_argument("--json", action="store_true", help="Print JSON.")
    show_persona.set_defaults(func=cmd_show_persona)

    forget = subparsers.add_parser("forget", help="Deactivate or delete a long-term memory.")
    forget.add_argument("memory_id", help="Long-term memory id.")
    forget.add_argument("--reason", default="User requested memory removal.", help="Reason stored in revision log.")
    forget.add_argument("--hard-delete", action="store_true", help="Delete instead of deactivating.")
    forget.set_defaults(func=cmd_forget)

    revise = subparsers.add_parser("revise", help="Manually revise a long-term memory.")
    revise.add_argument("memory_id", help="Long-term memory id.")
    revise.add_argument("--summary", help="New memory summary.")
    revise.add_argument("--category", help="New category.")
    revise.add_argument("--confidence", type=float, help="New confidence score.")
    revise.add_argument("--mutable", action="store_true", help="Mark the memory as mutable.")
    revise.add_argument("--immutable", action="store_true", help="Mark the memory as immutable.")
    revise.add_argument("--activate", action="store_true", help="Activate the memory.")
    revise.add_argument("--deactivate", action="store_true", help="Deactivate the memory.")
    revise.add_argument("--reason", default="Manual memory correction.", help="Revision reason.")
    revise.set_defaults(func=cmd_revise)

    export = subparsers.add_parser("export", help="Export all memory layers as JSON and Markdown.")
    export.add_argument("--output-dir", type=Path, default=None, help="Directory for export files. Defaults to ./exports.")
    export.set_defaults(func=cmd_export)

    return parser


def cmd_ingest(args: argparse.Namespace) -> int:
    storage = Storage(resolve_root(args.root))
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

    combined = sorted(id_index.values(), key=lambda item: (item.created_at, item.id))
    storage.save_memory_candidates(combined)
    print(f"Ingested {len(added_events)} new conversation events from {args.path}.")
    print(f"Extracted {len(extracted)} candidate memories.")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    storage = Storage(resolve_root(args.root))
    events = storage.load_conversation_events()
    existing_candidates = storage.load_memory_candidates()
    extractor = MemoryExtractor()
    candidates = extractor.extract_from_events(events, existing_candidates=existing_candidates)
    storage.save_memory_candidates(candidates)
    print(f"Rebuilt {len(candidates)} candidate memories from {len(events)} conversation events.")
    return 0


def cmd_consolidate(args: argparse.Namespace) -> int:
    storage = Storage(resolve_root(args.root))
    candidates = storage.load_memory_candidates()
    memories = storage.load_long_term_memory()
    consolidator = MemoryConsolidator()
    result = consolidator.consolidate(candidates, memories)
    storage.save_memory_candidates(result.candidates)
    storage.save_long_term_memory(result.memories)
    if result.revisions:
        storage.append_revisions(result.revisions)
    print(
        "Consolidation complete: "
        f"created={result.created}, updated={result.updated}, conflicts={result.conflicts}, pending={result.pending}."
    )
    return 0


def cmd_build_persona(args: argparse.Namespace) -> int:
    storage = Storage(resolve_root(args.root))
    memories = storage.load_long_term_memory()
    builder = PersonaBuilder()
    profile = builder.build(memories)
    storage.save_persona_profile(profile)
    if args.json:
        print(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(profile.markdown_summary)
    return 0


def cmd_show_memory(args: argparse.Namespace) -> int:
    storage = Storage(resolve_root(args.root))
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
        print(
            f"{memory.id} | {memory.category} | confidence={memory.confidence:.2f} | "
            f"reinforced={memory.reinforcement_count} | contradictions={memory.contradiction_count}"
        )
        print(f"  {memory.summary}")
        if memory.evidence:
            print(f"  evidence: {sentence_excerpt(memory.evidence[0].excerpt, 100)}")
    return 0


def cmd_show_persona(args: argparse.Namespace) -> int:
    storage = Storage(resolve_root(args.root))
    profile = storage.load_persona_profile()
    if profile is None:
        print("No persona profile built yet.")
        return 0
    if args.json:
        print(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(profile.markdown_summary)
    return 0


def cmd_forget(args: argparse.Namespace) -> int:
    storage = Storage(resolve_root(args.root))
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
        action = "forget"
        after = target.to_dict()

    storage.save_long_term_memory(memories)
    revision = RevisionEntry(
        id=f"rev_{stable_hash(f'{action}|{args.memory_id}|{utc_now()}')}",
        entity_type="long_term_memory",
        entity_id=args.memory_id,
        action=action,
        timestamp=utc_now(),
        reason=args.reason,
        before=before,
        after=after,
    )
    storage.append_revisions([revision])
    print(f"Memory {args.memory_id} {'deleted' if args.hard_delete else 'deactivated'}.")
    return 0


def cmd_revise(args: argparse.Namespace) -> int:
    storage = Storage(resolve_root(args.root))
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
    if args.activate:
        target.active = True
    if args.deactivate:
        target.active = False
    target.last_seen = utc_now()
    storage.save_long_term_memory(memories)
    revision = RevisionEntry(
        id=f"rev_{stable_hash(f'revise|{args.memory_id}|{utc_now()}')}",
        entity_type="long_term_memory",
        entity_id=args.memory_id,
        action="revise",
        timestamp=utc_now(),
        reason=args.reason,
        before=before,
        after=target.to_dict(),
    )
    storage.append_revisions([revision])
    print(f"Revised memory {args.memory_id}.")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    storage = Storage(resolve_root(args.root))
    output_dir = args.output_dir or (storage.root / "exports")
    output_dir.mkdir(parents=True, exist_ok=True)

    persona = storage.load_persona_profile()
    export_json = {
        "conversation_events": [event.to_dict() for event in storage.load_conversation_events()],
        "memory_candidates": [candidate.to_dict() for candidate in storage.load_memory_candidates()],
        "long_term_memory": [memory.to_dict() for memory in storage.load_long_term_memory()],
        "persona_profile": persona.to_dict() if persona else {},
        "revisions": [entry.to_dict() for entry in storage.load_revisions()],
    }
    json_path = output_dir / "personality-memory-export.json"
    markdown_path = output_dir / "personality-memory-export.md"
    write_json(json_path, export_json)
    markdown_path.write_text(build_export_markdown(export_json), encoding="utf-8")
    print(f"Exported JSON to {json_path}")
    print(f"Exported Markdown to {markdown_path}")
    return 0


def resolve_root(root: Path | None) -> Path:
    return detect_project_root(root)


def load_dialogue_payload(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_dialogue_payload(payload: Any) -> list[ConversationEvent]:
    conversations: list[dict[str, Any]]
    if isinstance(payload, dict) and "messages" in payload:
        conversations = [payload]
    elif isinstance(payload, list) and payload and all(isinstance(item, dict) and "speaker" in item for item in payload):
        conversations = [{"messages": payload}]
    elif isinstance(payload, list):
        conversations = payload
    else:
        raise ValueError("Dialogue file must contain a conversation object, a message list, or a list of conversations.")

    events: list[ConversationEvent] = []
    for conversation_index, conversation in enumerate(conversations):
        session_id = conversation.get("session_id") or f"session_{conversation_index + 1}"
        messages = conversation.get("messages", [])
        for message_index, message in enumerate(messages):
            message_id = str(message.get("message_id") or f"m{message_index + 1}")
            speaker = message.get("speaker", "user")
            text = message.get("text", "").strip()
            if not text:
                continue
            occurred_at = message.get("timestamp") or utc_now()
            event_id = f"evt_{stable_hash(f'{session_id}|{message_id}|{text}')}"
            events.append(
                ConversationEvent(
                    id=event_id,
                    session_id=session_id,
                    message_id=message_id,
                    speaker=speaker,
                    text=text,
                    occurred_at=occurred_at,
                )
            )
    return events


def find_memory(memories: list[LongTermMemory], memory_id: str) -> LongTermMemory | None:
    for memory in memories:
        if memory.id == memory_id:
            return memory
    return None


def build_export_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Personality Memory Export",
        "",
        f"- Conversation events: {len(payload['conversation_events'])}",
        f"- Memory candidates: {len(payload['memory_candidates'])}",
        f"- Long-term memories: {len(payload['long_term_memory'])}",
        f"- Revisions: {len(payload['revisions'])}",
        "",
        "## Long-Term Memory",
    ]
    if payload["long_term_memory"]:
        for memory in payload["long_term_memory"]:
            lines.append(
                f"- `{memory['id']}` [{memory['category']}] confidence={memory['confidence']}: {memory['summary']}"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Persona Profile"])
    persona = payload.get("persona_profile") or {}
    if persona:
        lines.append(persona.get("markdown_summary", "No Markdown summary stored."))
    else:
        lines.append("- No persona profile built.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
