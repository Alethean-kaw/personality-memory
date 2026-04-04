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
        self.assertIn("Persona Profile", profile.markdown_summary)


if __name__ == "__main__":
    unittest.main()
