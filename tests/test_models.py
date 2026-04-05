from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from personality_memory.models import (  # noqa: E402
    MemoryCandidate,
    PersonaProfile,
    PersonaSection,
    PersonaSignal,
    RetrievalHit,
    RetrievalResult,
    ReviewItem,
)


class MemoryCandidateModelTests(unittest.TestCase):
    def test_round_trips_resolution_metadata(self) -> None:
        candidate = MemoryCandidate(
            id="cand_1",
            content="prefers json outputs",
            type="preference",
            confidence=0.8,
            created_at="2026-03-01T09:00:00Z",
            status="accepted",
            notes="Merged into ltm_1",
            resolution_kind="merged",
            resolved_at="2026-03-02T09:00:00Z",
            resolved_memory_id="ltm_1",
        )

        restored = MemoryCandidate.from_dict(candidate.to_dict())

        self.assertEqual(restored.resolution_kind, "merged")
        self.assertEqual(restored.resolved_at, "2026-03-02T09:00:00Z")
        self.assertEqual(restored.resolved_memory_id, "ltm_1")

    def test_loads_old_style_payload_without_resolution_metadata(self) -> None:
        payload = {
            "id": "cand_legacy",
            "content": "prefers concise answers",
            "type": "style",
            "confidence": 0.8,
            "source_refs": [],
            "created_at": "2026-03-01T09:00:00Z",
            "status": "accepted",
            "notes": "Legacy payload",
        }

        restored = MemoryCandidate.from_dict(payload)

        self.assertIsNone(restored.resolution_kind)
        self.assertIsNone(restored.resolved_at)
        self.assertIsNone(restored.resolved_memory_id)


class PersonaModelTests(unittest.TestCase):
    def test_round_trips_contested_signal_metadata(self) -> None:
        signal = PersonaSignal(
            memory_id="ltm_1",
            summary="prefers concise responses",
            confidence=0.9,
            effective_confidence=0.78,
            contradiction_count=1,
        )

        restored = PersonaSignal.from_dict(signal.to_dict())

        self.assertEqual(restored.memory_id, "ltm_1")
        self.assertEqual(restored.effective_confidence, 0.78)
        self.assertEqual(restored.contradiction_count, 1)

    def test_loads_old_persona_payload_without_contested_signals(self) -> None:
        payload = {
            "generated_at": "2026-03-01T09:00:00Z",
            "memory_refs": ["ltm_1"],
            "communication_style": {"summary": "Signals suggest the user prefers concise answers."},
            "priorities": {"summary": "Not enough evidence about stable priorities yet."},
            "recurring_interests": {"summary": "No recurring projects or interests are durable yet."},
            "working_preferences": {"summary": "Not enough evidence about working preferences yet."},
            "emotional_tone_preferences": {"summary": "Not enough evidence about tone preferences yet."},
            "likely_goals": {"summary": "No durable long-range goals are confirmed yet."},
            "avoidances": {"summary": "No durable avoidances are confirmed yet."},
            "system_adaptation_notes": [],
            "markdown_summary": "# Persona Profile",
        }

        restored = PersonaProfile.from_dict(payload)

        self.assertEqual(restored.contested_signals, [])
        self.assertEqual(restored.communication_style.summary, "Signals suggest the user prefers concise answers.")

    def test_persona_profile_round_trips_contested_signals(self) -> None:
        profile = PersonaProfile(
            generated_at="2026-03-01T09:00:00Z",
            memory_refs=["ltm_1"],
            communication_style=PersonaSection(summary="Signals suggest the user prefers concise answers."),
            priorities=PersonaSection(summary="Not enough evidence about stable priorities yet."),
            recurring_interests=PersonaSection(summary="No recurring projects or interests are durable yet."),
            working_preferences=PersonaSection(summary="Not enough evidence about working preferences yet."),
            emotional_tone_preferences=PersonaSection(summary="Not enough evidence about tone preferences yet."),
            likely_goals=PersonaSection(summary="No durable long-range goals are confirmed yet."),
            avoidances=PersonaSection(summary="No durable avoidances are confirmed yet."),
            contested_signals=[
                PersonaSignal(
                    memory_id="ltm_2",
                    summary="prefers verbose responses",
                    confidence=0.93,
                    effective_confidence=0.57,
                    contradiction_count=3,
                )
            ],
            system_adaptation_notes=[],
            markdown_summary="# Persona Profile",
        )

        restored = PersonaProfile.from_dict(profile.to_dict())

        self.assertEqual(len(restored.contested_signals), 1)
        self.assertEqual(restored.contested_signals[0].memory_id, "ltm_2")
        self.assertEqual(restored.contested_signals[0].contradiction_count, 3)


class ReviewAndRetrievalModelTests(unittest.TestCase):
    def test_review_item_round_trips_revision_ids(self) -> None:
        review = ReviewItem(
            id="review_1",
            candidate_id="cand_1",
            target_memory_id="ltm_1",
            kind="conflict",
            reason="Potential contradiction.",
            opened_at="2026-03-01T09:00:00Z",
            status="resolved",
            resolution_action="merge-into",
            resolution_notes="Confirmed by user.",
            resolved_at="2026-03-01T09:10:00Z",
            revision_ids=["rev_1", "rev_2"],
        )

        restored = ReviewItem.from_dict(review.to_dict())

        self.assertEqual(restored.revision_ids, ["rev_1", "rev_2"])
        self.assertEqual(restored.resolution_action, "merge-into")

    def test_retrieval_result_round_trips_hits_and_open_reviews(self) -> None:
        payload = RetrievalResult(
            query="Need JSON output",
            generated_at="2026-03-01T09:00:00Z",
            memory_hits=[
                RetrievalHit(
                    memory_id="ltm_1",
                    summary="prefers json outputs",
                    category="preference",
                    confidence=0.86,
                    effective_confidence=0.86,
                    relevance_score=0.91,
                    supporting_evidence=["I prefer JSON output."],
                )
            ],
            persona_adaptation_notes=[{"note": "Use JSON when it helps clarity.", "memory_refs": ["ltm_1"], "strength": "strong"}],
            contested_signals=[
                PersonaSignal(
                    memory_id="ltm_2",
                    summary="prefers verbose prose",
                    confidence=0.9,
                    effective_confidence=0.54,
                    contradiction_count=3,
                )
            ],
            open_reviews=[
                ReviewItem(
                    id="review_open",
                    candidate_id="cand_2",
                    target_memory_id="ltm_2",
                    kind="conflict",
                    reason="Needs adjudication.",
                    opened_at="2026-03-01T10:00:00Z",
                )
            ],
        )

        restored = RetrievalResult.from_dict(payload.to_dict())

        self.assertEqual(restored.memory_hits[0].memory_id, "ltm_1")
        self.assertEqual(restored.contested_signals[0].memory_id, "ltm_2")
        self.assertEqual(restored.open_reviews[0].id, "review_open")


if __name__ == "__main__":
    unittest.main()
