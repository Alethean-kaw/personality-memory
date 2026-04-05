# Replay Eval: aging-revive-replay

- Backend: hybrid
- Passed: True
- Generated at: 2026-04-05T06:00:26Z

## Step 1
- Profile: default
- Dialogue: D:\GPT Codex\OpenClaw Skill\personality-memory\examples\dialogue_04_aging_start.json
- Counts: {'conversation_events': 1, 'memory_candidates': 1, 'long_term_memory': 1, 'open_reviews': 0}
### Invariants
- idempotence: passed=True
- terminal_support_ignored: passed=True
- inactive_not_retrieved: passed=True
- contested_separated: passed=True
- review_auditability: passed=True
- runtime_contract: passed=True

## Step 2
- Profile: default
- Dialogue: D:\GPT Codex\OpenClaw Skill\personality-memory\examples\dialogue_05_aging_checkpoint.json
- Counts: {'conversation_events': 2, 'memory_candidates': 2, 'long_term_memory': 2, 'open_reviews': 0}
### Retrieval Checks
- retrieval:archival note-taking engine: passed=True
### Memory Checks
- memory-step-2: passed=True
### Invariants
- idempotence: passed=True
- terminal_support_ignored: passed=True
- inactive_not_retrieved: passed=True
- contested_separated: passed=True
- review_auditability: passed=True
- runtime_contract: passed=True

## Step 3
- Profile: default
- Dialogue: D:\GPT Codex\OpenClaw Skill\personality-memory\examples\dialogue_06_aging_revive.json
- Counts: {'conversation_events': 3, 'memory_candidates': 3, 'long_term_memory': 2, 'open_reviews': 0}
### Retrieval Checks
- retrieval:archival note-taking engine: passed=True
### Memory Checks
- memory-step-3: passed=True
### Invariants
- idempotence: passed=True
- terminal_support_ignored: passed=True
- inactive_not_retrieved: passed=True
- contested_separated: passed=True
- review_auditability: passed=True
- runtime_contract: passed=True