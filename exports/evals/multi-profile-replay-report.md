# Replay Eval: multi-profile-replay

- Backend: hybrid
- Passed: True
- Generated at: 2026-04-05T06:00:25Z

## Step 1
- Profile: alpha
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
- Profile: beta
- Dialogue: D:\GPT Codex\OpenClaw Skill\personality-memory\examples\dialogue_02.json
- Counts: {'conversation_events': 4, 'memory_candidates': 6, 'long_term_memory': 5, 'open_reviews': 0}
### Retrieval Checks
- retrieval:local storage over cloud dependencies: passed=True
- retrieval:local storage over cloud dependencies: passed=True
### Memory Checks
- memory-step-2: passed=True
- memory-step-2: passed=True
### Invariants
- idempotence: passed=True
- terminal_support_ignored: passed=True
- inactive_not_retrieved: passed=True
- contested_separated: passed=True
- review_auditability: passed=True
- runtime_contract: passed=True