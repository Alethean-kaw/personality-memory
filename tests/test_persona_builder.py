from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from personality_memory.models import EvidenceRef, LongTermMemory  # noqa: E402
from personality_memory.persona_builder import PersonaBuilder  # noqa: E402


def make_ref(event_id: str) -> EvidenceRef:
    return EvidenceRef(
        conversation_event_id=event_id,
        session_id="s1",
        message_id=event_id,
        speaker="user",
        occurred_at="2026-03-01T09:00:00Z",
        excerpt="Example excerpt",
    )


class PersonaBuilderTests(unittest.TestCase):
    def test_builds_explainable_sections_and_notes(self) -> None:
        builder = PersonaBuilder()
        memories = [
            LongTermMemory(
                id="ltm_style",
                summary="prefers concise and structured responses",
                category="style",
                evidence=[make_ref("evt1")],
                confidence=0.9,
                first_seen="2026-03-01T09:00:00Z",
                last_seen="2026-03-02T09:00:00Z",
                reinforcement_count=2,
                contradiction_count=0,
                mutable=True,
                active=True,
            ),
            LongTermMemory(
                id="ltm_workflow",
                summary="uses python and terminal workflows",
                category="constraint",
                evidence=[make_ref("evt2")],
                confidence=0.82,
                first_seen="2026-03-01T09:00:00Z",
                last_seen="2026-03-02T09:00:00Z",
                reinforcement_count=2,
                contradiction_count=0,
                mutable=True,
                active=True,
            ),
            LongTermMemory(
                id="ltm_project",
                summary="works on local-first writing tools",
                category="project",
                evidence=[make_ref("evt3")],
                confidence=0.79,
                first_seen="2026-03-01T09:00:00Z",
                last_seen="2026-03-02T09:00:00Z",
                reinforcement_count=2,
                contradiction_count=0,
                mutable=True,
                active=True,
            ),
        ]

        profile = builder.build(memories)
        self.assertIn("concise", profile.communication_style.summary)
        self.assertIn("python", profile.working_preferences.summary)
        self.assertIn("local-first writing tools", profile.recurring_interests.summary)
        self.assertTrue(profile.system_adaptation_notes)
        self.assertEqual(profile.contested_signals, [])
        self.assertIn("Persona Profile", profile.markdown_summary)

    def test_contested_memories_move_to_dedicated_section(self) -> None:
        builder = PersonaBuilder()
        memories = [
            LongTermMemory(
                id="ltm_medium_style",
                summary="prefers concise responses",
                category="style",
                evidence=[make_ref("evt1")],
                confidence=0.9,
                first_seen="2026-03-01T09:00:00Z",
                last_seen="2026-03-02T09:00:00Z",
                reinforcement_count=3,
                contradiction_count=1,
                mutable=True,
                active=True,
            ),
            LongTermMemory(
                id="ltm_contested_style",
                summary="prefers verbose responses",
                category="style",
                evidence=[make_ref("evt2")],
                confidence=0.93,
                first_seen="2026-03-01T09:00:00Z",
                last_seen="2026-03-02T09:00:00Z",
                reinforcement_count=3,
                contradiction_count=3,
                mutable=True,
                active=True,
            ),
            LongTermMemory(
                id="ltm_workflow",
                summary="uses python and terminal workflows",
                category="constraint",
                evidence=[make_ref("evt3")],
                confidence=0.86,
                first_seen="2026-03-01T09:00:00Z",
                last_seen="2026-03-02T09:00:00Z",
                reinforcement_count=2,
                contradiction_count=0,
                mutable=True,
                active=True,
            ),
        ]

        profile = builder.build(memories)
        strong_ids = {signal.memory_id for signal in profile.communication_style.strong_signals}
        medium_ids = {signal.memory_id for signal in profile.communication_style.medium_signals}
        contested_ids = {signal.memory_id for signal in profile.contested_signals}
        note_refs = {memory_id for note in profile.system_adaptation_notes for memory_id in note["memory_refs"]}

        self.assertNotIn("ltm_contested_style", strong_ids)
        self.assertNotIn("ltm_contested_style", medium_ids)
        self.assertIn("ltm_medium_style", medium_ids)
        self.assertIn("ltm_contested_style", contested_ids)
        contested_signal = next(signal for signal in profile.contested_signals if signal.memory_id == "ltm_contested_style")
        self.assertEqual(contested_signal.contradiction_count, 3)
        self.assertLess(contested_signal.effective_confidence, contested_signal.confidence)
        self.assertNotIn("ltm_contested_style", note_refs)
        self.assertIn("Contested Signals", profile.markdown_summary)


if __name__ == "__main__":
    unittest.main()
