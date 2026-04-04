---
name: personality-memory
description: Persistent conversation-memory skill for extracting stable user preferences, projects, goals, working habits, and communication patterns from long-running dialogue. Use when Codex needs to ingest dialogue logs, build candidate memories, consolidate them into explainable long-term memory, generate a grounded persona profile, or revise/forget previously stored memory without relying on external databases or APIs.
---

# Personality Memory

Use the local Python package and CLI in this folder to maintain a durable, explainable memory system.

## Workflow

1. Ingest dialogue logs with `python -m personality_memory.cli ingest ...` or `personality-memory ingest ...`.
2. Re-run `extract` if the extraction rules change and candidate memories need rebuilding.
3. Run `consolidate` to promote repeated or high-confidence candidates into long-term memory.
4. Run `build-persona` to generate the structured persona profile plus a Markdown summary.
5. Use `show-memory`, `show-persona`, `forget`, `revise`, and `export` for inspection and correction.

## Storage

Keep all state in this skill directory:

- `data/conversations.jsonl`
- `data/memory_candidates.json`
- `data/long_term_memory.json`
- `data/persona_profile.json`
- `data/revisions.json`

## Implementation Notes

- The extractor is intentionally conservative and favors repeated, explicit, long-term signals over one-off requests.
- Candidate memory exists as a quarantine layer so uncertain signals can accumulate evidence before they become durable memory.
- Persona generation is derived from accepted long-term memory only, and each section keeps memory references so the profile stays explainable.

## Useful Entrypoints

- CLI: `src/personality_memory/cli.py`
- Extraction rules: `src/personality_memory/rules.py`
- Consolidation logic: `src/personality_memory/consolidator.py`
- Persona synthesis: `src/personality_memory/persona_builder.py`
- Demo runner: `scripts/demo.py`
