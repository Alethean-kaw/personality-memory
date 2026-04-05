from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from personality_memory.backends import get_backend, list_backends, register_backend  # noqa: E402
from personality_memory.consolidator import MemoryConsolidator  # noqa: E402
from personality_memory.models import EvidenceRef, LongTermMemory, MemoryCandidate  # noqa: E402
from personality_memory.retrieval import RetrievalService  # noqa: E402


@dataclass(slots=True, frozen=True)
class AlwaysSimilarBackend:
    name: str = "test-always-similar"

    def similarity(self, left: str, right: str) -> float:
        return 0.91 if left and right else 0.0


@dataclass(slots=True, frozen=True)
class MarkerBackend:
    name: str = "test-marker-backend"

    def similarity(self, left: str, right: str) -> float:
        return 0.98 if "[favorite]" in right.lower() else 0.05


def make_ref(event_id: str) -> EvidenceRef:
    return EvidenceRef(
        conversation_event_id=event_id,
        session_id="session-1",
        message_id=event_id,
        speaker="user",
        occurred_at="2026-03-01T09:00:00Z",
        excerpt="Example excerpt",
    )


class BackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        register_backend(AlwaysSimilarBackend())
        register_backend(MarkerBackend())

    def test_register_backend_adds_it_to_registry(self) -> None:
        self.assertIn("hybrid", list_backends())
        self.assertIn("test-always-similar", list_backends())
        self.assertEqual(get_backend().name, "hybrid")
        self.assertEqual(get_backend("test-marker-backend").name, "test-marker-backend")

    def test_hybrid_backend_scores_semantic_near_match_above_lexical(self) -> None:
        lexical = get_backend("lexical").similarity(
            "prefers local-first offline workflows",
            "likes offline local workflows",
        )
        hybrid = get_backend("hybrid").similarity(
            "prefers local-first offline workflows",
            "likes offline local workflows",
        )

        self.assertGreater(hybrid, lexical)

    def test_consolidator_honors_selected_backend(self) -> None:
        candidates = [
            MemoryCandidate(
                id="cand_a",
                content="alpha-only token stream",
                type="style",
                confidence=0.68,
                source_refs=[make_ref("evt1")],
                created_at="2026-03-01T09:00:00Z",
            ),
            MemoryCandidate(
                id="cand_b",
                content="beta-only fragment set",
                type="style",
                confidence=0.68,
                source_refs=[make_ref("evt2")],
                created_at="2026-03-02T09:00:00Z",
            ),
        ]

        lexical_result = MemoryConsolidator().consolidate(
            [MemoryCandidate.from_dict(item.to_dict()) for item in candidates],
            [],
            [],
        )
        backend_result = MemoryConsolidator(backend_name="test-always-similar").consolidate(
            [MemoryCandidate.from_dict(item.to_dict()) for item in candidates],
            [],
            [],
        )

        self.assertEqual(lexical_result.created, 0)
        self.assertEqual(lexical_result.pending, 2)
        self.assertEqual(backend_result.created, 1)
        self.assertEqual(backend_result.updated, 1)
        self.assertEqual(len(backend_result.memories), 1)

    def test_retrieval_honors_selected_backend(self) -> None:
        memories = [
            LongTermMemory(
                id="ltm_marker",
                summary="[favorite] opaque token",
                category="preference",
                evidence=[make_ref("evt3")],
                confidence=0.7,
                first_seen="2026-03-01T09:00:00Z",
                last_seen="2026-03-01T09:00:00Z",
                reinforcement_count=1,
                contradiction_count=0,
                mutable=True,
                active=True,
            ),
            LongTermMemory(
                id="ltm_confident",
                summary="ordinary note",
                category="preference",
                evidence=[make_ref("evt4")],
                confidence=0.94,
                first_seen="2026-03-01T09:00:00Z",
                last_seen="2026-03-01T09:00:00Z",
                reinforcement_count=1,
                contradiction_count=0,
                mutable=True,
                active=True,
            ),
        ]

        lexical_hits = RetrievalService().retrieve(query="task", memories=memories).memory_hits
        backend_hits = RetrievalService(backend_name="test-marker-backend").retrieve(query="task", memories=memories).memory_hits

        self.assertEqual(lexical_hits[0].memory_id, "ltm_confident")
        self.assertEqual(backend_hits[0].memory_id, "ltm_marker")


if __name__ == "__main__":
    unittest.main()
