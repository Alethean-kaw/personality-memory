# Replay Eval: conflict-review-replay

- Backend: hybrid
- Passed: False
- Generated at: 2026-04-05T05:45:47Z

## Step 1
- Profile: default
- Dialogue: D:\GPT Codex\OpenClaw Skill\personality-memory\examples\dialogue_01.json
- Counts: {'conversation_events': 4, 'memory_candidates': 6, 'long_term_memory': 6, 'open_reviews': 0}
### Retrieval Checks
- retrieval:concise and structured answers: passed=True
### Invariants
- idempotence: passed=True
- terminal_support_ignored: passed=True
- inactive_not_retrieved: passed=True
- contested_separated: passed=True
- review_auditability: passed=True
- runtime_contract: passed=True

## Step 2
- Profile: default
- Dialogue: D:\GPT Codex\OpenClaw Skill\personality-memory\examples\dialogue_03_conflict.json
- Counts: {'conversation_events': 6, 'memory_candidates': 7, 'long_term_memory': 6, 'open_reviews': 0}
### Actions
- Resolved review_31ff99881cbd with reject-candidate: passed=True
### Retrieval Checks
- retrieval:concise and structured answers: passed=True
### Memory Checks
- memory-step-2: passed=True
### Invariants
- idempotence: passed=False
- terminal_support_ignored: passed=True
- inactive_not_retrieved: passed=True
- contested_separated: passed=True
- review_auditability: passed=True
- runtime_contract: passed=True