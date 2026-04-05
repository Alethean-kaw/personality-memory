from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from personality_memory.governance import MemoryGovernanceManager  # noqa: E402
from personality_memory.models import EvidenceRef, LongTermMemory, MemoryCandidate, ReviewItem  # noqa: E402


def make_ref(event_id: str, excerpt: str = "Example excerpt") -> EvidenceRef:
    return EvidenceRef(
        conversation_event_id=event_id,
        session_id="session-1",
        message_id=event_id,
        speaker="user",
        occurred_at="2026-03-01T09:00:00Z",
        excerpt=excerpt,
    )


class GovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = MemoryGovernanceManager()

    def test_accept_candidate_creates_new_memory_and_resolves_review(self) -> None:
        candidate = MemoryCandidate(
            id="cand_accept",
            content="prefers explicit JSON schemas",
            type="preference",
            confidence=0.8,
            source_refs=[make_ref("evt1")],
            created_at="2026-03-02T09:00:00Z",
            status="review",
            notes="Needs manual approval.",
            resolution_kind="conflict",
            resolved_at="2026-03-02T09:05:00Z",
            resolved_memory_id=None,
        )
        review = ReviewItem(
            id="review_accept",
            candidate_id="cand_accept",
            target_memory_id=None,
            kind="manual_review",
            reason="Operator wants to approve this memory.",
            opened_at="2026-03-02T09:05:00Z",
        )

        result = self.manager.resolve_review(
            review_id="review_accept",
            action="accept-candidate",
            reason="Confirmed by the user.",
            candidates=[candidate],
            memories=[],
            review_items=[review],
        )

        self.assertEqual(len(result.memories), 1)
        self.assertTrue(result.memories[0].id.startswith("ltm_"))
        self.assertEqual(result.candidates[0].status, "accepted")
        self.assertEqual(result.candidates[0].resolution_kind, "accepted_by_review")
        self.assertEqual(result.review_items[0].status, "resolved")
        self.assertEqual(result.review_items[0].resolution_action, "accept-candidate")
        self.assertEqual(result.review_items[0].target_memory_id, result.memories[0].id)
        self.assertEqual(len(result.revisions), 3)
        self.assertEqual(set(result.review_items[0].revision_ids), {revision.id for revision in result.revisions})

    def test_merge_into_updates_target_memory(self) -> None:
        candidate = MemoryCandidate(
            id="cand_merge",
            content="prefers concise JSON outputs",
            type="style",
            confidence=0.79,
            source_refs=[make_ref("evt2", "Please keep answers concise and JSON-friendly.")],
            created_at="2026-03-03T09:00:00Z",
            status="review",
        )
        memory = LongTermMemory(
            id="ltm_style",
            summary="prefers concise outputs",
            category="style",
            evidence=[make_ref("evt0", "Please keep answers concise.")],
            confidence=0.83,
            first_seen="2026-03-01T09:00:00Z",
            last_seen="2026-03-01T09:00:00Z",
            reinforcement_count=1,
            contradiction_count=1,
            mutable=True,
            active=True,
        )
        review = ReviewItem(
            id="review_merge",
            candidate_id="cand_merge",
            target_memory_id="ltm_style",
            kind="conflict",
            reason="Needs a merge decision.",
            opened_at="2026-03-03T09:05:00Z",
        )

        result = self.manager.resolve_review(
            review_id="review_merge",
            action="merge-into",
            reason="User confirmed this was reinforcement, not contradiction.",
            candidates=[candidate],
            memories=[memory],
            review_items=[review],
            memory_id="ltm_style",
        )

        updated_memory = result.memories[0]
        self.assertEqual(updated_memory.id, "ltm_style")
        self.assertEqual(updated_memory.reinforcement_count, 2)
        self.assertGreater(updated_memory.confidence, 0.83)
        self.assertEqual(result.candidates[0].status, "accepted")
        self.assertEqual(result.candidates[0].resolved_memory_id, "ltm_style")
        self.assertEqual(result.review_items[0].status, "resolved")
        self.assertEqual(result.review_items[0].target_memory_id, "ltm_style")

    def test_replace_memory_overwrites_summary_and_category(self) -> None:
        candidate = MemoryCandidate(
            id="cand_replace",
            content="prefers markdown tables for dense comparisons",
            type="preference",
            confidence=0.77,
            source_refs=[make_ref("evt3", "I prefer markdown tables for dense comparisons.")],
            created_at="2026-03-04T09:00:00Z",
            status="review",
        )
        memory = LongTermMemory(
            id="ltm_old",
            summary="prefers bullet lists",
            category="style",
            evidence=[make_ref("evt_old", "Please use bullet lists.")],
            confidence=0.74,
            first_seen="2026-03-01T09:00:00Z",
            last_seen="2026-03-01T09:00:00Z",
            reinforcement_count=1,
            contradiction_count=3,
            mutable=False,
            active=False,
        )
        review = ReviewItem(
            id="review_replace",
            candidate_id="cand_replace",
            target_memory_id="ltm_old",
            kind="manual_review",
            reason="The old memory should be replaced.",
            opened_at="2026-03-04T09:05:00Z",
        )

        result = self.manager.resolve_review(
            review_id="review_replace",
            action="replace-memory",
            reason="User explicitly corrected the stored preference.",
            candidates=[candidate],
            memories=[memory],
            review_items=[review],
            memory_id="ltm_old",
        )

        updated_memory = result.memories[0]
        self.assertEqual(updated_memory.summary, "prefers markdown tables for dense comparisons")
        self.assertEqual(updated_memory.category, "preference")
        self.assertEqual(updated_memory.contradiction_count, 0)
        self.assertTrue(updated_memory.active)
        self.assertEqual(result.candidates[0].resolution_kind, "replaced_by_review")

    def test_reject_candidate_marks_terminal(self) -> None:
        candidate = MemoryCandidate(
            id="cand_reject",
            content="prefers verbose essays",
            type="style",
            confidence=0.73,
            source_refs=[make_ref("evt4")],
            created_at="2026-03-05T09:00:00Z",
            status="review",
        )
        review = ReviewItem(
            id="review_reject",
            candidate_id="cand_reject",
            target_memory_id="ltm_style",
            kind="conflict",
            reason="This looks hypothetical.",
            opened_at="2026-03-05T09:05:00Z",
        )

        result = self.manager.resolve_review(
            review_id="review_reject",
            action="reject-candidate",
            reason="User said this statement should not become long-term memory.",
            candidates=[candidate],
            memories=[],
            review_items=[review],
        )

        self.assertEqual(result.candidates[0].status, "rejected")
        self.assertEqual(result.candidates[0].resolution_kind, "rejected_by_review")
        self.assertEqual(result.review_items[0].status, "resolved")
        self.assertEqual(result.review_items[0].resolution_action, "reject-candidate")

    def test_reopen_candidate_dismisses_open_review_and_clears_resolution_metadata(self) -> None:
        candidate = MemoryCandidate(
            id="cand_reopen",
            content="prefers verbose essays",
            type="style",
            confidence=0.73,
            source_refs=[make_ref("evt5")],
            created_at="2026-03-05T09:00:00Z",
            status="review",
            notes="Potential contradiction.",
            resolution_kind="conflict",
            resolved_at="2026-03-05T09:06:00Z",
            resolved_memory_id="ltm_style",
        )
        review = ReviewItem(
            id="review_reopen",
            candidate_id="cand_reopen",
            target_memory_id="ltm_style",
            kind="conflict",
            reason="Requires another pass.",
            opened_at="2026-03-05T09:05:00Z",
        )

        result = self.manager.reopen_candidate(
            candidate_id="cand_reopen",
            reason="The user clarified that this should be reevaluated later.",
            candidates=[candidate],
            review_items=[review],
            memories=[],
        )

        reopened = result.candidates[0]
        self.assertEqual(reopened.status, "candidate")
        self.assertIsNone(reopened.resolution_kind)
        self.assertIsNone(reopened.resolved_at)
        self.assertIsNone(reopened.resolved_memory_id)
        self.assertEqual(result.review_items[0].status, "dismissed")
        self.assertEqual(result.review_items[0].resolution_action, "reopen-candidate")
        self.assertEqual(len(result.revisions), 2)


if __name__ == "__main__":
    unittest.main()
