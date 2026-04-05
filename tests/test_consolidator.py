from __future__ import annotations

import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from personality_memory.cli import main as cli_main  # noqa: E402
from personality_memory.consolidator import MemoryConsolidator  # noqa: E402
from personality_memory.models import EvidenceRef, LongTermMemory, MemoryCandidate  # noqa: E402
from personality_memory.storage import Storage  # noqa: E402


def make_ref(event_id: str, occurred_at: str = "2026-03-01T09:00:00Z") -> EvidenceRef:
    return EvidenceRef(
        conversation_event_id=event_id,
        session_id="s1",
        message_id=event_id,
        speaker="user",
        occurred_at=occurred_at,
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

        result = consolidator.consolidate(candidates, [], [])
        self.assertEqual(result.created, 1)
        self.assertEqual(result.updated, 1)
        self.assertEqual(len(result.memories), 1)
        self.assertEqual(result.memories[0].reinforcement_count, 2)
        self.assertEqual(result.review_items, [])

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

        result = consolidator.consolidate([candidate], [memory], [])
        self.assertEqual(result.conflicts, 1)
        self.assertEqual(result.candidates[0].status, "review")
        self.assertEqual(result.memories[0].contradiction_count, 1)
        self.assertEqual(result.candidates[0].resolution_kind, "conflict")
        self.assertEqual(result.candidates[0].resolved_memory_id, "ltm_1")
        self.assertIsNotNone(result.candidates[0].resolved_at)
        self.assertEqual(len(result.review_items), 1)
        self.assertEqual(result.review_items[0].candidate_id, "cand_conflict")
        self.assertEqual(result.review_items[0].target_memory_id, "ltm_1")
        self.assertEqual(result.review_items[0].status, "open")

    def test_conflict_review_items_are_not_duplicated_on_rerun(self) -> None:
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

        first = consolidator.consolidate([candidate], [memory], [])
        second = consolidator.consolidate(first.candidates, first.memories, first.review_items)

        self.assertEqual(len(first.review_items), 1)
        self.assertEqual(len(second.review_items), 1)
        self.assertEqual(second.review_items[0].to_dict(), first.review_items[0].to_dict())

    def test_does_not_auto_merge_immutable_memory(self) -> None:
        consolidator = MemoryConsolidator()
        memory = LongTermMemory(
            id="ltm_locked",
            summary="prefers concise answers",
            category="style",
            evidence=[make_ref("evt1")],
            confidence=0.88,
            first_seen="2026-03-01T09:00:00Z",
            last_seen="2026-03-01T09:00:00Z",
            reinforcement_count=1,
            contradiction_count=0,
            mutable=False,
            active=True,
        )
        candidate = MemoryCandidate(
            id="cand_locked",
            content="prefers concise answers",
            type="style",
            confidence=0.82,
            source_refs=[make_ref("evt2")],
            created_at="2026-03-10T09:00:00Z",
        )

        result = consolidator.consolidate([candidate], [memory], [])

        self.assertEqual(result.updated, 0)
        self.assertEqual(result.created, 0)
        self.assertEqual(result.memories[0].summary, "prefers concise answers")
        self.assertEqual(result.memories[0].reinforcement_count, 1)
        self.assertEqual(result.memories[0].last_seen, "2026-03-01T09:00:00Z")
        self.assertEqual(result.candidates[0].status, "accepted")
        self.assertEqual(result.candidates[0].resolution_kind, "matched_immutable")
        self.assertEqual(result.candidates[0].resolved_memory_id, "ltm_locked")
        self.assertIsNotNone(result.candidates[0].resolved_at)
        self.assertIn("immutable memory", result.candidates[0].notes)

        first_candidate = result.candidates[0].to_dict()
        first_memory = result.memories[0].to_dict()
        second = consolidator.consolidate(result.candidates, result.memories, result.review_items)
        self.assertEqual(second.candidates[0].to_dict(), first_candidate)
        self.assertEqual(second.memories[0].to_dict(), first_memory)

    def test_review_candidates_are_not_replayed(self) -> None:
        consolidator = MemoryConsolidator()
        memory = LongTermMemory(
            id="ltm_conflict",
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
            id="cand_conflict_repeat",
            content="prefers verbose answers",
            type="style",
            confidence=0.82,
            source_refs=[make_ref("evt3")],
            created_at="2026-03-10T09:00:00Z",
        )

        first = consolidator.consolidate([candidate], [memory], [])
        first_candidate = first.candidates[0].to_dict()
        first_memory = first.memories[0].to_dict()
        first_review = first.review_items[0].to_dict()
        second = consolidator.consolidate(first.candidates, first.memories, first.review_items)

        self.assertEqual(second.candidates[0].to_dict(), first_candidate)
        self.assertEqual(second.memories[0].to_dict(), first_memory)
        self.assertEqual(second.review_items[0].to_dict(), first_review)

    def test_terminal_candidates_do_not_influence_pending_support(self) -> None:
        consolidator = MemoryConsolidator()
        candidates = [
            MemoryCandidate(
                id="cand_old",
                content="prefers concise answers",
                type="style",
                confidence=0.68,
                source_refs=[make_ref("evt1")],
                created_at="2026-03-01T09:00:00Z",
                status="accepted",
                notes="Merged already.",
                resolution_kind="merged",
                resolved_at="2026-03-01T10:00:00Z",
                resolved_memory_id="ltm_1",
            ),
            MemoryCandidate(
                id="cand_new",
                content="prefers concise answers",
                type="style",
                confidence=0.66,
                source_refs=[make_ref("evt2")],
                created_at="2026-03-02T09:00:00Z",
            ),
        ]

        result = consolidator.consolidate(candidates, [], [])

        self.assertEqual(result.created, 0)
        self.assertEqual(result.pending, 1)
        self.assertEqual(result.candidates[1].status, "candidate")
        self.assertIn("support=1", result.candidates[1].notes)
        self.assertEqual(result.memories, [])

    def test_merges_use_parsed_timestamp_order(self) -> None:
        consolidator = MemoryConsolidator()
        memory = LongTermMemory(
            id="ltm_time",
            summary="prefers concise answers",
            category="style",
            evidence=[make_ref("evt1", occurred_at="2026-03-01 9:00")],
            confidence=0.88,
            first_seen="2026-03-01 9:00",
            last_seen="2026-03-01 9:00",
            reinforcement_count=1,
            contradiction_count=0,
            mutable=True,
            active=True,
        )
        candidate = MemoryCandidate(
            id="cand_time",
            content="prefers concise answers",
            type="style",
            confidence=0.82,
            source_refs=[make_ref("evt2", occurred_at="2026-03-01 10:00")],
            created_at="2026-03-01 10:00",
        )

        result = consolidator.consolidate([candidate], [memory], [])

        self.assertEqual(result.updated, 1)
        self.assertEqual(result.memories[0].last_seen, "2026-03-01T10:00:00Z")

    def test_consolidate_is_idempotent_via_cli(self) -> None:
        root = ROOT / f".tmp-idempotence-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        try:
            (root / "skill.yaml").write_text("name: test-skill\n", encoding="utf-8")
            dialogue_path = root / "dialogue.json"
            payload = {
                "session_id": "session-1",
                "messages": [
                    {
                        "message_id": "m1",
                        "speaker": "user",
                        "timestamp": "2026-03-01T09:00:00Z",
                        "text": "I'm building a local-first writing tool for tabletop campaigns. Please keep answers concise and structured.",
                    },
                    {
                        "message_id": "m2",
                        "speaker": "user",
                        "timestamp": "2026-03-15T09:00:00Z",
                        "text": "I'm still working on the local-first writing tool for tabletop campaigns.",
                    },
                ],
            }
            dialogue_path.write_text(json.dumps(payload), encoding="utf-8")

            cli_main(["--root", str(root), "ingest", str(dialogue_path)])
            cli_main(["--root", str(root), "extract"])
            cli_main(["--root", str(root), "consolidate"])

            storage = Storage(root)
            first_memories = [item.to_dict() for item in storage.load_long_term_memory()]
            first_candidates = [item.to_dict() for item in storage.load_memory_candidates()]
            first_reviews = [item.to_dict() for item in storage.load_review_items()]

            cli_main(["--root", str(root), "consolidate"])

            second_memories = [item.to_dict() for item in storage.load_long_term_memory()]
            second_candidates = [item.to_dict() for item in storage.load_memory_candidates()]
            second_reviews = [item.to_dict() for item in storage.load_review_items()]

            self.assertEqual(second_memories, first_memories)
            self.assertEqual(second_candidates, first_candidates)
            self.assertEqual(second_reviews, first_reviews)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
