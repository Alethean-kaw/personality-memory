# personality-memory

`personality-memory` is a self-contained OpenClaw skill and Python CLI for turning long-running dialogue into durable, explainable user memory.

This MVP is intentionally conservative:

- It stores every raw conversation event.
- It extracts candidate memories before promoting anything to long-term memory.
- It builds persona from accepted long-term memory only.
- It keeps revision history for manual correction, deactivation, and deletion.
- It uses local JSON and JSONL files only.

No external database, embedding service, or API is required.

## What This Skill Is

This skill is not a one-shot chat summarizer.

It is a persistent memory pipeline for:

- accumulating raw dialogue over time
- extracting stable signals while filtering short-term noise
- consolidating reinforced evidence into long-term memory
- generating a structured persona profile that stays grounded in real evidence
- supporting later correction, overwrite, deactivation, and export

## Why Memory Is Not The Same As Persona

Memory and persona should not be collapsed into the same thing.

- Memory is evidence: explicit preferences, recurring projects, repeated goals, stable routines, taboos, and constraints.
- Persona is a model built from memory: a structured operational interpretation of how the assistant should adapt.

If memory is treated as persona directly, the system becomes too eager to label the user, overfits to single messages, and turns transient statements into false identity claims.

This MVP keeps the layers separate on purpose:

- `conversation_events` preserves the raw facts.
- `memory_candidates` holds hypotheses that still need evidence.
- `long_term_memory` contains accepted durable signals.
- `persona_profile` is a downstream synthesis, not a source of truth.

## Why The Candidate Layer Exists

The candidate layer is a quarantine buffer between raw text and durable memory.

Without it, one-off instructions like "just do this quickly today" can become fake long-term preferences.

This layer helps by:

- attaching source evidence to every extraction
- letting low-support signals stay unpromoted
- preserving ambiguity until repetition or manual review resolves it
- making it possible to reject, revise, or mark outdated extractions later

## How This MVP Reduces Hallucinated Persona Inference

This version avoids aggressive inference in several ways:

- It only extracts from explicit self-disclosure patterns.
- It filters temporal and one-off language such as `today`, `for now`, `temporary`, and task-like requests.
- It requires evidence-backed candidates before promotion.
- It keeps pending candidates instead of forcing every signal into long-term memory.
- Persona sections are built from accepted memories only.
- Persona JSON includes memory references and confidence buckets so each section is explainable.

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
      cli.py
      models.py
      storage.py
      extractor.py
      consolidator.py
      persona_builder.py
      scoring.py
      rules.py
      utils.py
  data/
    conversations.jsonl
    memory_candidates.json
    long_term_memory.json
    persona_profile.json
    revisions.json
  examples/
    dialogue_01.json
    dialogue_02.json
  scripts/
    demo.py
  tests/
    test_extractor.py
    test_consolidator.py
    test_persona_builder.py
```

`exports/` is created on demand by the `export` command.

## Memory Layers

### A. `conversation_events`

Stored in `data/conversations.jsonl`.

Each event contains:

- `id`
- `session_id`
- `message_id`
- `speaker`
- `text`
- `occurred_at`

### B. `memory_candidates`

Stored in `data/memory_candidates.json`.

Each candidate contains:

- `id`
- `content`
- `type`
- `confidence`
- `source_refs`
- `created_at`
- `status`
- `notes`

Supported statuses in the MVP:

- `candidate`
- `accepted`
- `review`
- `rejected`
- `outdated`

### C. `long_term_memory`

Stored in `data/long_term_memory.json`.

Each long-term memory contains:

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

### D. `persona_profile`

Stored in `data/persona_profile.json`.

The generated persona contains:

- `communication_style`
- `priorities`
- `recurring_interests`
- `working_preferences`
- `emotional_tone_preferences`
- `likely_goals`
- `avoidances`
- `system_adaptation_notes`

Each major section includes:

- a readable summary
- strong / medium / weak signal lists
- source memory references via `memory_id`

The JSON also stores a Markdown summary string so the same profile can be displayed in human-readable form.

## Data Flow

```text
dialogue JSON
  -> ingest
  -> conversation_events
  -> extractor
  -> memory_candidates
  -> consolidate
  -> long_term_memory
  -> build-persona
  -> persona_profile
```

Manual correction path:

```text
forget / revise
  -> long_term_memory update
  -> revisions.json append
  -> build-persona again if needed
```

## Extraction Rules

The extractor is rule-based and deliberately conservative.

It currently favors explicit statements like:

- `I prefer ...`
- `I dislike ...`
- `Please keep answers ...`
- `I'm building ...`
- `I'm still working on ...`
- `I value ...`
- `I often ...`
- `I mainly use ...`

It supports both English and a small set of Chinese phrasing patterns.

Current candidate categories:

- `preference`
- `identity`
- `project`
- `style`
- `constraint`
- `relationship_pattern` reserved for future extension
- `worldview`
- `goal`
- `taboo`
- `routine`

## Consolidation Rules

The consolidator supports:

- similarity-based merge for repeated candidate memories
- confidence increase on reinforcement
- evidence accumulation
- contradiction counting and review state for conflicting signals
- manual deactivation or hard deletion with revision logs
- manual revision with before/after snapshots in `revisions.json`

Important MVP behavior:

- repeated high-confidence signals get promoted or reinforced
- low-support signals can stay in `candidate` state
- conflicting signals are not auto-overwritten

## Quick Start

### 1. Install

```bash
python -m pip install -e .
```

### 2. Run The Demo

```bash
python scripts/demo.py
```

### 3. Use The CLI

```bash
personality-memory ingest ./examples/dialogue_01.json
personality-memory ingest ./examples/dialogue_02.json
personality-memory extract
personality-memory consolidate
personality-memory build-persona
personality-memory show-memory
personality-memory show-persona
personality-memory export
```

If you do not want to install the package, you can adapt the demo pattern and run the CLI by inserting `src/` into `PYTHONPATH`.

## CLI Commands

### `ingest`

Ingest a conversation file and immediately extract candidates from newly added events.

```bash
personality-memory ingest ./examples/dialogue_01.json
```

Supported file shapes:

- one conversation object with `messages`
- one list of messages
- one list of conversation objects

### `extract`

Rebuild candidates from stored conversation events.

```bash
personality-memory extract
```

### `consolidate`

Merge accepted candidates into long-term memory and leave weak candidates pending.

```bash
personality-memory consolidate
```

### `build-persona`

Build the current persona profile from long-term memory.

```bash
personality-memory build-persona
personality-memory build-persona --json
```

### `show-memory`

Show current long-term memory.

```bash
personality-memory show-memory
personality-memory show-memory --json
personality-memory show-memory --include-inactive
```

### `show-persona`

Show the current persona profile.

```bash
personality-memory show-persona
personality-memory show-persona --json
```

### `forget`

Deactivate or delete a memory.

```bash
personality-memory forget ltm_8bacb9c052af --reason "User said this is no longer true"
personality-memory forget ltm_8bacb9c052af --hard-delete --reason "Remove completely"
```

### `revise`

Manually correct a memory while preserving a revision record.

```bash
personality-memory revise ltm_2b0baf9345a8 --summary "prefers structured JSON outputs" --reason "User clarified the preference"
```

### `export`

Export the full state bundle as JSON and Markdown.

```bash
personality-memory export
personality-memory export --output-dir ./exports
```

## Example Dialogues

Two example inputs are included:

- [examples/dialogue_01.json](./examples/dialogue_01.json)
- [examples/dialogue_02.json](./examples/dialogue_02.json)

They intentionally repeat some signals so the demo can show reinforcement.

## Example Stage Outputs

These snippets come from the actual verified demo run in this repository.

### Stage 1: Raw Conversation Events

`data/conversations.jsonl` contains one JSON object per line, for example:

```json
{
  "id": "evt_e2fa5eaa5dd9",
  "session_id": "campaign-tool-session-01",
  "message_id": "m1",
  "speaker": "user",
  "text": "I'm building a local-first writing tool for tabletop campaigns. Please keep answers concise and structured. I prefer JSON when it makes things clearer.",
  "occurred_at": "2026-03-01T09:00:00Z"
}
```

### Stage 2: Candidate Memory

After `ingest` and `extract`, candidates look like this:

```json
{
  "id": "cand_1fb4165cfce7",
  "content": "uses python and terminal workflows",
  "type": "constraint",
  "confidence": 0.67,
  "status": "candidate",
  "notes": "Needs more evidence (support=1)"
}
```

This is exactly why the candidate layer exists: the signal is plausible, but it only appeared once, so the system keeps it as a candidate rather than forcing it into long-term memory.

### Stage 3: Long-Term Memory

After `consolidate`, a reinforced memory looks like this:

```json
{
  "id": "ltm_8bacb9c052af",
  "summary": "works on local-first writing tool for tabletop campaigns",
  "category": "project",
  "confidence": 0.99,
  "first_seen": "2026-03-01T09:00:00Z",
  "last_seen": "2026-03-15T10:00:00Z",
  "reinforcement_count": 2,
  "contradiction_count": 0,
  "mutable": true,
  "active": true
}
```

That same project appeared twice, so it was merged and reinforced instead of duplicated.

### Stage 4: Persona Profile JSON

After `build-persona`, the persona contains evidence-backed sections:

```json
{
  "communication_style": {
    "summary": "Signals suggest the user prefers concise and structured, prefers direct and concise, avoids fluffy marketing language, and prefers json when it makes things clearer."
  },
  "system_adaptation_notes": [
    {
      "note": "Default to concise, structured answers and use JSON or explicit formats when it improves clarity.",
      "memory_refs": [
        "ltm_97c142d058aa",
        "ltm_4b8a345308ca",
        "ltm_2b0baf9345a8"
      ],
      "strength": "strong"
    }
  ]
}
```

### Stage 5: Persona Markdown

The same persona can be shown as Markdown:

```md
## Communication Style
- Signals suggest the user prefers concise and structured, prefers direct and concise, avoids fluffy marketing language, and prefers json when it makes things clearer.

## System Adaptation Notes
- Default to concise, structured answers and use JSON or explicit formats when it improves clarity.
```

## Verified Demo Results

The current demo run completes with:

- `ingest`: 8 conversation events written
- `extract`: 12 candidate memories rebuilt
- `consolidate`: `created=10`, `updated=1`, `conflicts=0`, `pending=1`
- `build-persona`: persona JSON and Markdown summary written
- `export`: JSON and Markdown export bundle written to `exports/`

## Testing

Run unit tests:

```bash
python -m unittest discover -s tests -v
```

Validated in this workspace:

- extractor tests pass
- consolidator tests pass
- persona builder tests pass
- demo script runs end to end
- `revise` and `forget` command paths were manually exercised
- skill metadata passes `quick_validate.py`

## Design Tradeoffs In This MVP

This is an MVP, so a few tradeoffs are explicit:

- The extractor is heuristic and pattern-based, not semantic.
- The system favors false negatives over false positives.
- Persona is intentionally high-level and avoids speculative identity claims.
- Some memories that feel "probably true" will remain candidates until repeated.
- There is no embedding, reranking, or LLM summarization dependency yet.

These are deliberate choices to keep the first version transparent, testable, local, and easy to debug.

## Extension Points

This codebase is designed so future upgrades can be added without changing the storage contract:

- add embeddings for better similarity matching
- add reranking for candidate promotion
- add LLM-backed summarization for cleaner memory summaries
- add richer contradiction handling with explicit conflict objects
- add candidate aging and decay
- add per-user namespaces beyond session-level ingestion
- add retrieval helpers for downstream assistants

Good extension seams:

- extraction rules: `src/personality_memory/rules.py`
- confidence and similarity logic: `src/personality_memory/scoring.py`
- consolidation behavior: `src/personality_memory/consolidator.py`
- persona synthesis: `src/personality_memory/persona_builder.py`

## Notes On Persistence

All persistent state lives under `data/` inside this skill directory, so the memory survives restarts as long as the directory is preserved.

No external service is required.
