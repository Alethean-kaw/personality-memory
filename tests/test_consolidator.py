from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from personality_memory.consolidator import MemoryConsolidator  # noqa: E402
from personality_memory.models import EvidenceRef, LongTermMemory, MemoryCandidate  # noqa: E402


def make_ref(event_id: str) -> EvidenceRef:
    return EvidenceRef(
        conversation_event_id=event_id,
        session_id="s1",
        message_id=event_id,
        speaker="user",
        occurred_at="2026-03-01T09:00:00Z",
        excerpt="Example excerpt",
    )


class ConsolidatorTests(unittest.TestCase):
    def test_promotes_and_reinforces_repeated_candidates(self) -> None:
        consolidator = MemoryConsolidator()
        candidates = [
            MemoryCandidate(
                id="cand_a",
                content="prefers concise and structured responses",
                type="style",
                confidence=0.78,
                source_refs=[make_ref("evt1")],
                created_at="2026-03-01T09:00:00Z",
            ),
            MemoryCandidate(
                id="cand_b",
                content="prefers concise, structured responses",
                type="style",
                confidence=0.8,
                source_refs=[make_ref("evt2")],
                created_at="2026-03-02T09:00:00Z",
            ),
        ]

        result = consolidator.consolidate(candidates, [])
        self.assertEqual(result.created, 1)
        self.assertEqual(result.updated, 1)
        self.assertEqual(len(result.memories), 1)
        self.assertEqual(result.memories[0].reinforcement_count, 2)

    def test_marks_conflicts_for_review(self) -> None:
        consolidator = MemoryConsolidator()
        memory = LongTermMemory(
            id="ltm_1",
            summary="prefers concise answers",
            category="style",
            evidence=[make_ref("evt1")],
            confidence=0.88,
            first_seen="2026-03-01T09:00:00Z",
            last_seen="2026-03-01T09:00:00Z",
            reinforcement_count=1,
            contradiction_count=0,
            mutable=True,
            active=True,
        )
        candidate = MemoryCandidate(
            id="cand_conflict",
            content="prefers verbose answers",
            type="style",
            confidence=0.82,
            source_refs=[make_ref("evt3")],
            created_at="2026-03-10T09:00:00Z",
        )

        result = consolidator.consolidate([candidate], [memory])
        self.assertEqual(result.conflicts, 1)
        self.assertEqual(result.candidates[0].status, "review")
        self.assertEqual(result.memories[0].contradiction_count, 1)


if __name__ == "__main__":
    unittest.main()
