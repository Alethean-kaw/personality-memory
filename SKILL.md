---
name: personality-memory
description: Persistent conversation-memory skill for extracting stable user preferences, projects, goals, working habits, and communication patterns from long-running dialogue. Use when Codex needs to ingest dialogue logs, build candidate memories, consolidate them into explainable long-term memory, generate a grounded persona profile, retrieve runtime context, manage multiple profiles, arbitrate conflicts through review items, or run replay evaluations without relying on external databases or APIs.
---

# Personality Memory

Use the local Python package and CLI in this folder to maintain a durable, explainable, profile-aware memory system.

## Recommended Runtime Flow

1. Call `python -m personality_memory.cli retrieve-context --query ...` or `personality-memory retrieve-context --query ...` before generating a personalized answer.
2. Treat the returned JSON as the machine contract for runtime personalization.
3. Use `prepare-context` only when you need a human-readable Markdown rendering for prompt injection or debugging.
4. Use `build-persona` to refresh the persisted persona snapshot when memory state changes materially.

## Workflow

1. Run `migrate-storage` once or let storage auto-migrate legacy flat `data/*` into `data/profiles/default/`.
2. Use `list-profiles`, `create-profile`, `show-profile`, and `set-default-profile` to manage isolated personas.
3. Ingest dialogue with `ingest`, and re-run `extract` if rules change.
4. Run `consolidate` to promote repeated or high-confidence candidates into long-term memory, revive dormant memories when reinforced, and open review items for conflicts.
5. Run `build-persona` to generate the structured persona profile and Markdown summary.
6. Use `retrieve-context` / `prepare-context` to prepare grounded assistant context for new tasks.
7. Use `list-review`, `show-review`, `resolve-review`, and `reopen-candidate` to arbitrate unresolved conflicts.
8. Use `show-memory`, `show-persona`, `forget`, `revise`, `replay-eval`, and `export` for inspection, correction, and evaluation.

## Storage

Keep all state in this skill directory:

- `data/registry.json`
- `data/migrations.json`
- `data/profiles/<profile_id>/conversations.jsonl`
- `data/profiles/<profile_id>/memory_candidates.json`
- `data/profiles/<profile_id>/long_term_memory.json`
- `data/profiles/<profile_id>/persona_profile.json`
- `data/profiles/<profile_id>/review_items.json`
- `data/profiles/<profile_id>/revisions.json`
- `data/legacy_backup/v1-flat/` for auto-migrated backups

## Implementation Notes

- The extractor is conservative and prefers explicit, repeated, long-term signals over one-off requests.
- Candidate memory exists as a quarantine layer so uncertain signals can accumulate evidence before becoming durable memory.
- Persona generation is derived from accepted active long-term memory only, while contested memories are separated into `contested_signals`.
- `retrieve-context` is the stable runtime contract for downstream assistant use.
- Retrieval and consolidation share a pluggable similarity backend; `hybrid` is the default and `lexical` remains available for comparison.
- Lifecycle aging hides dormant / expired memories from default persona and retrieval output without deleting them.
- Review items make conflicts auditable and manually resolvable without silently overwriting memory.

## Useful Entrypoints

- CLI: `src/personality_memory/cli.py`
- Storage and migration: `src/personality_memory/storage.py`
- Lifecycle aging: `src/personality_memory/lifecycle.py`
- Retrieval contract: `src/personality_memory/retrieval.py`
- Review governance: `src/personality_memory/governance.py`
- Replay evaluator: `src/personality_memory/evaluator.py`
- Backends registry: `src/personality_memory/backends.py`
- Consolidation logic: `src/personality_memory/consolidator.py`
- Persona synthesis: `src/personality_memory/persona_builder.py`
- Demo runner: `scripts/demo.py`
