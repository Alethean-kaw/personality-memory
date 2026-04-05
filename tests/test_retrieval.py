from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from personality_memory.models import EvidenceRef, LongTermMemory, ReviewItem  # noqa: E402
from personality_memory.retrieval import RetrievalService  # noqa: E402
from personality_memory.storage import SCHEMA_VERSION  # noqa: E402


def make_ref(event_id: str, excerpt: str) -> EvidenceRef:
    return EvidenceRef(
        conversation_event_id=event_id,
        session_id="session-1",
        message_id=event_id,
        speaker="user",
        occurred_at="2026-03-01T09:00:00Z",
        excerpt=excerpt,
    )


class RetrievalServiceTests(unittest.TestCase):
    def test_retrieves_stable_hits_and_separates_uncertain_sections(self) -> None:
        memories = [
            LongTermMemory(
                id="ltm_stable",
                summary="prefers concise json outputs",
                category="style",
                evidence=[make_ref("evt1", "Please keep answers concise and JSON-friendly.")],
                confidence=0.88,
                first_seen="2026-03-01T09:00:00Z",
                last_seen="2026-03-02T09:00:00Z",
                reinforcement_count=3,
                contradiction_count=0,
                mutable=True,
                active=True,
            ),
            LongTermMemory(
                id="ltm_inactive",
                summary="prefers GUI dashboards",
                category="preference",
                evidence=[make_ref("evt2", "I prefer GUI dashboards for this workflow.")],
                confidence=0.95,
                first_seen="2026-03-01T09:00:00Z",
                last_seen="2026-03-03T09:00:00Z",
                reinforcement_count=2,
                contradiction_count=0,
                mutable=True,
                active=False,
            ),
            LongTermMemory(
                id="ltm_contested",
                summary="prefers verbose and detailed answers",
                category="style",
                evidence=[make_ref("evt3", "Please keep answers verbose and detailed.")],
                confidence=0.91,
                first_seen="2026-03-01T09:00:00Z",
                last_seen="2026-03-04T09:00:00Z",
                reinforcement_count=2,
                contradiction_count=3,
                mutable=True,
                active=True,
            ),
        ]
        review_items = [
            ReviewItem(
                id="review_1",
                candidate_id="cand_conflict",
                target_memory_id="ltm_stable",
                kind="conflict",
                reason="Potential contradiction requires review.",
                opened_at="2026-03-04T10:00:00Z",
            )
        ]

        service = RetrievalService()
        result = service.retrieve(
            query="Need concise JSON output for the next answer.",
            memories=memories,
            review_items=review_items,
            profile_id="writer",
            top_k=5,
            include_contested=True,
            include_review=True,
        )

        self.assertEqual(result.schema_version, SCHEMA_VERSION)
        self.assertEqual(result.profile_id, "writer")
        self.assertEqual([hit.memory_id for hit in result.memory_hits], ["ltm_stable"])
        self.assertEqual([signal.memory_id for signal in result.contested_signals], ["ltm_contested"])
        self.assertEqual([item.id for item in result.open_reviews], ["review_1"])
        self.assertTrue(result.persona_adaptation_notes)
        self.assertIn("ltm_stable", result.persona_adaptation_notes[0]["memory_refs"])
        self.assertTrue(result.usage_guidance)
        self.assertEqual(result.memory_policy["default_backend"], "hybrid")

        markdown = service.render_markdown(result)
        self.assertIn("## Relevant Long-Term Memory", markdown)
        self.assertIn("## Contested / Uncertain Signals", markdown)
        self.assertIn("## Open Review Items", markdown)
        self.assertIn("do not present them as confirmed facts", markdown)

    def test_can_exclude_contested_and_review_sections(self) -> None:
        memory = LongTermMemory(
            id="ltm_style",
            summary="prefers direct markdown outputs",
            category="style",
            evidence=[make_ref("evt4", "Please keep responses direct and in Markdown.")],
            confidence=0.84,
            first_seen="2026-03-01T09:00:00Z",
            last_seen="2026-03-01T09:00:00Z",
            reinforcement_count=1,
            contradiction_count=0,
            mutable=True,
            active=True,
        )
        contested = LongTermMemory(
            id="ltm_contested",
            summary="prefers lengthy freeform prose",
            category="style",
            evidence=[make_ref("evt5", "Please keep responses lengthy and freeform.")],
            confidence=0.9,
            first_seen="2026-03-01T09:00:00Z",
            last_seen="2026-03-05T09:00:00Z",
            reinforcement_count=2,
            contradiction_count=2,
            mutable=True,
            active=True,
        )
        review = ReviewItem(
            id="review_2",
            candidate_id="cand_2",
            target_memory_id=None,
            kind="manual_review",
            reason="Needs a human decision.",
            opened_at="2026-03-05T10:00:00Z",
        )

        service = RetrievalService()
        result = service.retrieve(
            query="Need direct Markdown output.",
            memories=[memory, contested],
            review_items=[review],
            include_contested=False,
            include_review=False,
        )

        self.assertEqual([hit.memory_id for hit in result.memory_hits], ["ltm_style"])
        self.assertEqual(result.contested_signals, [])
        self.assertEqual(result.open_reviews, [])


if __name__ == "__main__":
    unittest.main()
