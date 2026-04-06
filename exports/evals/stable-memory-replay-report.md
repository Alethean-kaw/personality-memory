# Replay Eval: stable-memory-replay

- Backend: hybrid
- Passed: True
- Generated at: 2026-04-06T12:22:54Z

## Step 1
- Profile: default
- Dialogue: D:\GPT Codex\OpenClaw Skill\personality-memory\examples\dialogue_01.json
- Counts: {'conversation_events': 4, 'memory_candidates': 6, 'long_term_memory': 6, 'open_reviews': 0}
### Retrieval Checks
- retrieval:tabletop campaigns: passed=True
### Invariants
- idempotence: passed=True
- terminal_support_ignored: passed=True
- inactive_not_retrieved: passed=True
- contested_separated: passed=True
- review_auditability: passed=True
- runtime_contract: passed=True

## Step 2
- Profile: default
- Dialogue: D:\GPT Codex\OpenClaw Skill\personality-memory\examples\dialogue_02.json
- Counts: {'conversation_events': 8, 'memory_candidates': 11, 'long_term_memory': 10, 'open_reviews': 0}
### Retrieval Checks
- retrieval:local storage over cloud dependencies: passed=True
### Memory Checks
- memory-step-2: passed=True
### Invariants
- idempotence: passed=True
- terminal_support_ignored: passed=True
- inactive_not_retrieved: passed=True
- contested_separated: passed=True
- review_auditability: passed=True
- runtime_contract: passed=True