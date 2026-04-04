from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from personality_memory.extractor import MemoryExtractor  # noqa: E402
from personality_memory.models import ConversationEvent  # noqa: E402


class MemoryExtractorTests(unittest.TestCase):
    def test_extracts_stable_preferences_and_projects(self) -> None:
        extractor = MemoryExtractor()
        event = ConversationEvent(
            id="evt_1",
            session_id="s1",
            message_id="m1",
            speaker="user",
            text="I'm building a local-first writing tool. Please keep answers concise and structured. I prefer JSON output.",
            occurred_at="2026-03-01T09:00:00Z",
        )

        candidates = extractor.extract_from_event(event)
        contents = {candidate.content for candidate in candidates}
        types = {candidate.type for candidate in candidates}

        self.assertIn("works on local-first writing tool", contents)
        self.assertIn("prefers concise and structured", contents)
        self.assertIn("prefers json output", contents)
        self.assertIn("project", types)
        self.assertIn("style", types)
        self.assertIn("preference", types)

    def test_rejects_short_term_noise(self) -> None:
        extractor = MemoryExtractor()
        event = ConversationEvent(
            id="evt_2",
            session_id="s1",
            message_id="m2",
            speaker="user",
            text="Please avoid this today and fix this bug right now.",
            occurred_at="2026-03-01T09:05:00Z",
        )
        candidates = extractor.extract_from_event(event)
        self.assertEqual(candidates, [])


if __name__ == "__main__":
    unittest.main()
