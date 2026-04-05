from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from personality_memory.consolidator import MemoryConsolidator  # noqa: E402
from personality_memory.lifecycle import apply_memory_lifecycle, refresh_memory_activity  # noqa: E402
from personality_memory.models import EvidenceRef, LongTermMemory, MemoryCandidate  # noqa: E402
from personality_memory.persona_builder import PersonaBuilder  # noqa: E402
from personality_memory.retrieval import RetrievalService  # noqa: E402


def make_ref(event_id: str, occurred_at: str = "2026-01-01T09:00:00Z", excerpt: str = "Example excerpt") -> EvidenceRef:
    return EvidenceRef(
        conversation_event_id=event_id,
        session_id="aging-session",
        message_id=event_id,
        speaker="user",
        occurred_at=occurred_at,
        excerpt=excerpt,
    )


class LifecycleTests(unittest.TestCase):
    def test_project_memory_ages_out_of_retrieval_and_persona(self) -> None:
        memory = LongTermMemory(
            id="ltm_project",
            summary="works on archival note-taking engine for narrative campaigns",
            category="project",
            evidence=[make_ref("evt1", excerpt="I'm building an archival note-taking engine for narrative campaigns.")],
            confidence=0.88,
            first_seen="2026-01-01T09:00:00Z",
            last_seen="2026-01-01T09:00:00Z",
            reinforcement_count=1,
            contradiction_count=0,
            mutable=True,
            active=True,
        )

        apply_memory_lifecycle(memory, reference_time="2026-07-15T09:00:00Z")
        result = RetrievalService().retrieve(
            query="archival note-taking engine",
            memories=[memory],
            reference_time="2026-07-15T09:00:00Z",
        )
        profile = PersonaBuilder().build([memory], reference_time="2026-07-15T09:00:00Z")

        self.assertFalse(memory.active)
        self.assertEqual(memory.lifecycle_state, "expired")
        self.assertEqual(result.memory_hits, [])
        self.assertNotIn("ltm_project", profile.memory_refs)

    def test_reinforcement_revives_expired_memory(self) -> None:
        memory = LongTermMemory(
            id="ltm_project",
            summary="works on archival note-taking engine for narrative campaigns",
            category="project",
            evidence=[make_ref("evt1", excerpt="I'm building an archival note-taking engine for narrative campaigns.")],
            confidence=0.88,
            first_seen="2026-01-01T09:00:00Z",
            last_seen="2026-01-01T09:00:00Z",
            reinforcement_count=1,
            contradiction_count=0,
            mutable=True,
            active=True,
        )
        apply_memory_lifecycle(memory, reference_time="2026-07-15T09:00:00Z")
        candidate = MemoryCandidate(
            id="cand_revive",
            content="works on archival note-taking engine for narrative campaigns",
            type="project",
            confidence=0.8,
            source_refs=[make_ref("evt2", occurred_at="2026-07-20T09:00:00Z", excerpt="I'm still working on the archival note-taking engine for narrative campaigns.")],
            created_at="2026-07-20T09:00:00Z",
        )

        result = MemoryConsolidator().consolidate([candidate], [memory], [], reference_time="2026-07-20T09:00:00Z")

        self.assertEqual(result.updated, 1)
        self.assertEqual(result.candidates[0].status, "accepted")
        self.assertIn("Revived and merged", result.candidates[0].notes)
        self.assertTrue(result.memories[0].active)
        self.assertEqual(result.memories[0].lifecycle_state, "active")
        self.assertEqual(result.memories[0].id, "ltm_project")

    def test_refresh_memory_activity_reactivates_hidden_memory(self) -> None:
        memory = LongTermMemory(
            id="ltm_hidden",
            summary="prefers local-only tooling",
            category="preference",
            evidence=[make_ref("evt3")],
            confidence=0.9,
            first_seen="2026-01-01T09:00:00Z",
            last_seen="2026-01-01T09:00:00Z",
            reinforcement_count=1,
            contradiction_count=0,
            mutable=True,
            active=False,
            lifecycle_state="expired",
            staleness_score=1.0,
            stale_since="2026-07-01T09:00:00Z",
        )

        refresh_memory_activity(memory, reference_time="2026-07-20T09:00:00Z")

        self.assertTrue(memory.active)
        self.assertEqual(memory.lifecycle_state, "active")
        self.assertEqual(memory.staleness_score, 0.0)
        self.assertIsNone(memory.stale_since)


if __name__ == "__main__":
    unittest.main()
