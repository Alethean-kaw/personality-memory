# personality-memory

`personality-memory` is a self-contained OpenClaw skill and local Python CLI for building a durable, explainable, profile-aware memory system from long-running dialogue.

This version is aimed at the first real product layer beyond an MVP:

- profile-aware storage with automatic migration from legacy flat `data/*`
- durable memory and persona separated into explicit layers
- lifecycle / aging for long-term memory instead of a single `active` flag
- review governance for conflict resolution and manual arbitration
- a stable runtime JSON contract for downstream assistant use
- local pluggable similarity backends with `hybrid` as the default
- replay evaluation for stability, isolation, migration, and aging scenarios

No external database, external API, or model download is required.

## What This Skill Is

This skill is not a one-shot chat summarizer.

It is a persistent memory pipeline for:

- collecting raw dialogue over time
- extracting candidate memory conservatively
- promoting reinforced evidence into long-term memory
- generating a structured persona profile grounded in memory
- retrieving relevant context for future assistant actions
- supporting correction, overwrite, deactivation, review, export, and replay evaluation

## Why Memory Is Not Persona

Memory and persona should stay separate.

- Memory is evidence: preferences, projects, routines, constraints, goals, taboos, worldview signals.
- Persona is an operational adaptation model built from accepted memory.

If the system treats memory as persona directly, it overfits to single messages and starts inventing identity-like claims from weak evidence. This skill keeps them distinct on purpose:

- `conversation_events` preserves raw facts.
- `memory_candidates` stores hypotheses.
- `long_term_memory` stores durable accepted signals.
- `persona_profile` is a downstream synthesis, not a source of truth.

## Why The Candidate Layer Exists

The candidate layer is a quarantine buffer between raw dialogue and durable memory.

Without it, one-off requests like `just do this for today` or temporary emotional states would get frozen into long-term personalization.

The candidate layer helps by:

- attaching evidence to every extraction
- keeping low-support signals pending
- allowing review/reject/reopen flows
- preserving traceability and idempotence with explicit resolution metadata

## How This Version Reduces Hallucinated Persona Inference

This version stays conservative in a few ways:

- extraction is rule-based and favors explicit self-disclosure
- temporal and one-off noise is filtered aggressively
- promotion requires reinforcement or sufficient confidence
- persona is built from active long-term memory only
- contested memories are separated into `contested_signals`
- dormant / expired memories are hidden from default persona and retrieval output
- retrieval returns review items and contested signals as explicitly uncertain sections

## Project Structure

```text
personality-memory/
  README.md
  SKILL.md
  skill.yaml
  pyproject.toml
  agents/
    openai.yaml
  src/
    personality_memory/
      __init__.py
      __main__.py
      backends.py
      cli.py
      consolidator.py
      evaluator.py
      extractor.py
      governance.py
      lifecycle.py
      memory_ops.py
      models.py
      persona_builder.py
      retrieval.py
      rules.py
      scoring.py
      storage.py
      utils.py
  data/
    registry.json
    migrations.json
    profiles/
      <profile_id>/
        conversations.jsonl
        memory_candidates.json
        long_term_memory.json
        persona_profile.json
        review_items.json
        revisions.json
    legacy_backup/
      v1-flat/
  examples/
    dialogue_01.json
    dialogue_02.json
    dialogue_03_conflict.json
    dialogue_04_aging_start.json
    dialogue_05_aging_checkpoint.json
    dialogue_06_aging_revive.json
    eval_stable.json
    eval_conflict.json
    eval_multi_profile.json
    eval_migration.json
    eval_aging.json
    legacy_seed_v1/
      *.json
  exports/
    personality-memory-export.json
    personality-memory-export.md
    evals/
      *.json
      *.md
  scripts/
    demo.py
  tests/
    test_backends.py
    test_cli.py
    test_consolidator.py
    test_evaluator.py
    test_extractor.py
    test_governance.py
    test_lifecycle.py
    test_models.py
    test_persona_builder.py
    test_retrieval.py
    test_storage.py
    test_utils.py
```

## Storage Layout And Migration

All persistence stays inside this skill directory by default.

Current storage layout:

- `data/registry.json`
- `data/migrations.json`
- `data/profiles/<profile_id>/conversations.jsonl`
- `data/profiles/<profile_id>/memory_candidates.json`
- `data/profiles/<profile_id>/long_term_memory.json`
- `data/profiles/<profile_id>/persona_profile.json`
- `data/profiles/<profile_id>/review_items.json`
- `data/profiles/<profile_id>/revisions.json`

### Registry

`registry.json` tracks:

- `schema_version`
- `default_profile_id`
- `profiles[]`

Each profile stores:

- `id`
- `display_name`
- `created_at`
- `updated_at`
- `backend`
- `aging_policy`

### Legacy Migration

If the skill starts and detects an old flat layout under `data/*`, it will:

1. create the `default` profile
2. copy old files into `data/legacy_backup/v1-flat/`
3. move them into `data/profiles/default/`
4. write a migration record into `data/migrations.json`

Migration is idempotent. Reopening the skill does not duplicate the migration or damage the data.

## Memory Layers

### `conversation_events`

Raw dialogue events with:

- `id`
- `session_id`
- `message_id`
- `speaker`
- `text`
- `occurred_at`

### `memory_candidates`

Candidate memories with:

- `id`
- `content`
- `type`
- `confidence`
- `source_refs`
- `created_at`
- `status`
- `notes`
- `resolution_kind`
- `resolved_at`
- `resolved_memory_id`

Statuses:

- `candidate`
- `accepted`
- `review`
- `rejected`
- `outdated`

### `long_term_memory`

Durable memory with:

- `id`
- `summary`
- `category`
- `evidence`
- `confidence`
- `first_seen`
- `last_seen`
- `reinforcement_count`
- `contradiction_count`
- `mutable`
- `active`
- `last_reinforced_at`
- `lifecycle_state`
- `staleness_score`
- `stale_since`
- `superseded_by`

### `persona_profile`

Derived persona with:

- `communication_style`
- `priorities`
- `recurring_interests`
- `working_preferences`
- `emotional_tone_preferences`
- `likely_goals`
- `avoidances`
- `contested_signals`
- `system_adaptation_notes`
- `markdown_summary`

### `review_items`

Auditable conflict and manual review records with:

- `id`
- `candidate_id`
- `target_memory_id`
- `kind`
- `reason`
- `opened_at`
- `status`
- `resolution_action`
- `resolution_notes`
- `resolved_at`
- `revision_ids`

## Runtime Contract For OpenClaw

`retrieve-context` is the stable machine contract for assistant runtime use.

The recommended flow is:

1. call `retrieve-context` before generating a personalized answer
2. use the returned JSON as the authoritative memory context bundle
3. only use `prepare-context` when you need a human-readable Markdown rendering

### `retrieve-context` JSON shape

```json
{
  "schema_version": 2,
  "profile_id": "default",
  "query": "Need concise JSON guidance",
  "generated_at": "2026-03-15T10:02:00Z",
  "memory_hits": [],
  "persona_adaptation_notes": [],
  "contested_signals": [],
  "open_reviews": [],
  "usage_guidance": [],
  "memory_policy": {}
}
```

Semantics:

- `memory_hits` are stable active memories only
- `contested_signals` are explicitly unsettled
- `open_reviews` are unresolved governance items
- `usage_guidance` explains how to treat the payload safely
- `memory_policy` describes the active backend / lifecycle assumptions

## Lifecycle / Aging

Long-term memory now uses lifecycle state instead of a single binary flag.

Supported states:

- `active`
- `dormant`
- `expired`

Default aging policy:

- `identity`: does not age automatically
- `style`, `preference`, `taboo`, `worldview`: dormant at 180 days, expired at 360 days
- `project`, `goal`, `routine`, `constraint`: dormant at 90 days, expired at 180 days

Lifecycle recalculation happens automatically during:

- `consolidate`
- `build-persona`
- `retrieve-context`
- `prepare-context`

Default retrieval and persona behavior:

- `active` memories are eligible for main output
- `dormant` and `expired` memories stay stored but are hidden by default
- if new evidence reinforces a dormant / expired memory, the consolidator revives it and resets it to `active`

## Consolidation And Governance Rules

### Consolidation

Important behavior:

- only pending `status == "candidate"` entries are auto-processed
- `accepted`, `review`, `rejected`, and `outdated` are terminal for automatic consolidation
- pending support scoring ignores all terminal candidates
- immutable memories are never auto-overwritten
- repeat `consolidate` runs on unchanged data are idempotent
- dormant / expired memories can be revived by new reinforcing candidates

### Governance

Manual review actions:

- `accept-candidate`
- `merge-into`
- `replace-memory`
- `reject-candidate`
- `reopen-candidate`

Every action appends to `revisions.json` so review decisions remain auditable.

## Backends

Similarity and ranking are pluggable.

Built-in backends:

- `hybrid` (default)
- `lexical`

`hybrid` combines:

- lexical similarity
- weighted token overlap
- char trigram similarity
- evidence excerpt matching
- contradiction penalty downstream in retrieval/persona scoring

The same backend seam is used by:

- consolidation
- retrieval
- replay evaluation

## Quick Start

### Install

```bash
python -m pip install -e .
```

### Run The Demo

```bash
python scripts/demo.py
```

### Basic Flow

```bash
personality-memory migrate-storage
personality-memory list-profiles
personality-memory ingest ./examples/dialogue_01.json
personality-memory ingest ./examples/dialogue_02.json
personality-memory extract
personality-memory consolidate
personality-memory build-persona
personality-memory retrieve-context --query "Need concise JSON guidance"
personality-memory prepare-context --query "Need concise JSON guidance"
personality-memory export
```

If you do not install the package, you can run `python -m personality_memory.cli ...` with `src/` on `PYTHONPATH`.

## CLI Commands

### Global Options

Most commands accept:

- `--root <path>`
- `--profile <profile_id>`

If `--profile` is omitted, the registry default profile is used.

### Profile / Storage Management

```bash
personality-memory list-profiles
personality-memory create-profile writer-alt --display-name "Writer Alt"
personality-memory show-profile writer-alt
personality-memory set-default-profile writer-alt
personality-memory migrate-storage --json
```

### Ingest / Extract / Consolidate

```bash
personality-memory ingest ./examples/dialogue_01.json
personality-memory extract
personality-memory consolidate
personality-memory consolidate --backend lexical
```

Accepted `timestamp` formats are normalized to canonical UTC `YYYY-MM-DDTHH:MM:SSZ`:

- ISO 8601 / RFC3339 with `Z` or explicit offset
- `YYYY-MM-DD HH:MM[:SS]`
- `YYYY/MM/DD HH:MM[:SS]`
- `YYYY-MM-DD`
- `YYYY/MM/DD`

### Persona / Retrieval

```bash
personality-memory build-persona
personality-memory build-persona --json
personality-memory retrieve-context --query "Need concise JSON guidance"
personality-memory prepare-context --query "Need concise JSON guidance"
```

### Review Governance

```bash
personality-memory list-review --status open
personality-memory show-review review_abcd1234 --json
personality-memory resolve-review review_abcd1234 --action reject-candidate --reason "Hypothetical statement"
personality-memory reopen-candidate cand_1234 --reason "Need to re-evaluate after new evidence"
```

### Manual Memory Control

```bash
personality-memory show-memory
personality-memory show-memory --include-inactive
personality-memory show-persona
personality-memory forget ltm_1234 --reason "No longer true"
personality-memory revise ltm_1234 --summary "prefers structured JSON outputs" --activate --reason "User clarified preference"
```

### Evaluation / Export

```bash
personality-memory replay-eval ./examples/eval_stable.json
personality-memory replay-eval ./examples/eval_multi_profile.json
personality-memory replay-eval ./examples/eval_migration.json
personality-memory replay-eval ./examples/eval_aging.json
personality-memory export
personality-memory export --all-profiles
```

## Example Dialogues And Replay Manifests

Dialogues:

- `examples/dialogue_01.json`
- `examples/dialogue_02.json`
- `examples/dialogue_03_conflict.json`
- `examples/dialogue_04_aging_start.json`
- `examples/dialogue_05_aging_checkpoint.json`
- `examples/dialogue_06_aging_revive.json`

Replay manifests:

- `examples/eval_stable.json`: repeated stable preferences and projects
- `examples/eval_conflict.json`: conflict creation plus manual review resolution
- `examples/eval_multi_profile.json`: profile isolation across `alpha` and `beta`
- `examples/eval_migration.json`: legacy flat storage migration with seeded memory
- `examples/eval_aging.json`: expiration and later revival of a project memory

## Verified Outputs

Representative examples from the current pipeline:

### Long-Term Memory

```json
{
  "id": "ltm_8bacb9c052af",
  "summary": "works on local-first writing tool for tabletop campaigns",
  "category": "project",
  "confidence": 0.99,
  "reinforcement_count": 2,
  "lifecycle_state": "active",
  "active": true
}
```

### Retrieval Contract

```json
{
  "schema_version": 2,
  "profile_id": "default",
  "query": "Need concise JSON guidance for the tabletop writing tool",
  "memory_hits": [
    {
      "memory_id": "ltm_8bacb9c052af",
      "summary": "works on local-first writing tool for tabletop campaigns",
      "category": "project"
    }
  ],
  "contested_signals": [],
  "open_reviews": []
}
```

### Prepared Context

```md
## Relevant Long-Term Memory
- [ltm_8bacb9c052af] (project) works on local-first writing tool for tabletop campaigns

## Usage Guidance
- Treat Relevant Long-Term Memory as durable guidance grounded in prior interaction.
- Treat contested signals and open review items as uncertain; do not present them as confirmed facts.
```

## Replay Evaluation Invariants

Built-in invariants currently check:

- consolidate idempotence
- terminal candidates do not influence support
- inactive memories are not retrieved
- contested memories stay out of normal hits
- open review items remain auditable
- runtime contract fields remain present and stable

## Testing

Run all tests:

```bash
python -m unittest discover -s tests -v
```

Validated in this workspace:

- 56 unit tests pass
- replay evaluator covers stable, conflict, migration, multi-profile, and aging scenarios
- retrieval, governance, storage migration, and lifecycle tests all pass

## Design Tradeoffs In This Version

This is still a conservative local system, so some tradeoffs are intentional:

- extraction is heuristic rather than model-based
- the system prefers false negatives over false positives
- persona avoids speculative identity claims
- manual review resolution is explicit and CLI-driven
- `hybrid` is local and lightweight, not embedding-based
- dormant / expired memory is hidden by default rather than deleted

## Extension Points

Natural future extensions include:

- local embedding or reranking backends
- richer review queues and reviewer policies
- candidate aging / decay
- optional LLM summarization for cleaner memory summaries
- tighter host integration that calls `retrieve-context` automatically before every response
- richer replay benchmark suites for long-horizon behavior

Useful code entrypoints:

- `src/personality_memory/storage.py`
- `src/personality_memory/cli.py`
- `src/personality_memory/consolidator.py`
- `src/personality_memory/lifecycle.py`
- `src/personality_memory/retrieval.py`
- `src/personality_memory/governance.py`
- `src/personality_memory/evaluator.py`

## Notes On Persistence

When the CLI is run without `--root`, it resolves to this bundled skill directory instead of the caller's current working directory.

Use `--root` only when you intentionally want to point at another compatible skill data directory.

All persistence remains local to the skill directory.
