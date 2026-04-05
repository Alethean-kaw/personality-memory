# Replay Eval: migration-seeded-replay

- Backend: hybrid
- Passed: True
- Generated at: 2026-04-05T06:00:25Z

## Step 1
- Profile: default
- Dialogue: D:\GPT Codex\OpenClaw Skill\personality-memory\examples\dialogue_01.json
- Counts: {'conversation_events': 4, 'memory_candidates': 6, 'long_term_memory': 7, 'open_reviews': 0}
### Retrieval Checks
- retrieval:local-only tooling: passed=True
### Memory Checks
- memory-step-1: passed=True
### Invariants
- idempotence: passed=True
- terminal_support_ignored: passed=True
- inactive_not_retrieved: passed=True
- contested_separated: passed=True
- review_auditability: passed=True
- runtime_contract: passed=True