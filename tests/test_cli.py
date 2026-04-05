from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from personality_memory.cli import normalize_dialogue_payload  # noqa: E402


class CliNormalizationTests(unittest.TestCase):
    def test_treats_flat_message_list_without_speaker_as_user_messages(self) -> None:
        payload = [{"text": "I prefer JSON output."}]

        events = normalize_dialogue_payload(payload)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].speaker, "user")
        self.assertEqual(events[0].text, "I prefer JSON output.")

    def test_normalizes_supported_timestamp_formats(self) -> None:
        cases = [
            ("2026-03-01T09:00:00Z", "2026-03-01T09:00:00Z"),
            ("2026-03-01 09:00", "2026-03-01T09:00:00Z"),
            ("2026-03-01 09:00:05", "2026-03-01T09:00:05Z"),
            ("2026/03/01 09:00", "2026-03-01T09:00:00Z"),
            ("2026/03/01 09:00:05", "2026-03-01T09:00:05Z"),
            ("2026-03-01", "2026-03-01T00:00:00Z"),
            ("2026/03/01", "2026-03-01T00:00:00Z"),
            ("2026-03-01T09:00:00+08:00", "2026-03-01T01:00:00Z"),
        ]

        for raw_timestamp, expected in cases:
            with self.subTest(raw_timestamp=raw_timestamp):
                payload = [{"session_id": "s1", "messages": [{"speaker": "user", "text": "hello", "timestamp": raw_timestamp}]}]
                events = normalize_dialogue_payload(payload)
                self.assertEqual(events[0].occurred_at, expected)

    def test_rejects_invalid_timestamp_string(self) -> None:
        payload = [{"session_id": "s1", "messages": [{"speaker": "user", "text": "hello", "timestamp": "not-a-time"}]}]

        with self.assertRaisesRegex(ValueError, "invalid 'timestamp'"):
            normalize_dialogue_payload(payload)

    def test_rejects_non_object_conversation_entries(self) -> None:
        payload = [{"messages": []}, "bad-entry"]

        with self.assertRaisesRegex(ValueError, "Conversation at index 1"):
            normalize_dialogue_payload(payload)

    def test_rejects_non_list_messages(self) -> None:
        payload = [{"session_id": "s1", "messages": "not-a-list"}]

        with self.assertRaisesRegex(ValueError, "invalid 'messages'"):
            normalize_dialogue_payload(payload)

    def test_rejects_top_level_dict_list_that_is_not_message_shaped(self) -> None:
        payload = [{"session_id": "s1"}]

        with self.assertRaisesRegex(ValueError, "must look like message objects"):
            normalize_dialogue_payload(payload)

    def test_rejects_non_object_message_entries(self) -> None:
        payload = [{"session_id": "s1", "messages": ["bad-message"]}]

        with self.assertRaisesRegex(ValueError, "message index 0"):
            normalize_dialogue_payload(payload)

    def test_rejects_non_string_message_text(self) -> None:
        payload = [{"session_id": "s1", "messages": [{"speaker": "user", "text": 42}]}]

        with self.assertRaisesRegex(ValueError, "invalid 'text'"):
            normalize_dialogue_payload(payload)

    def test_rejects_non_string_message_speaker(self) -> None:
        payload = [{"session_id": "s1", "messages": [{"speaker": 42, "text": "hello"}]}]

        with self.assertRaisesRegex(ValueError, "invalid 'speaker'"):
            normalize_dialogue_payload(payload)

    def test_rejects_non_string_message_timestamp(self) -> None:
        payload = [{"session_id": "s1", "messages": [{"speaker": "user", "text": "hello", "timestamp": 42}]}]

        with self.assertRaisesRegex(ValueError, "invalid 'timestamp'"):
            normalize_dialogue_payload(payload)

    def test_normalizes_session_id_to_string(self) -> None:
        payload = [{"session_id": 7, "messages": [{"speaker": "user", "text": "hello"}]}]

        events = normalize_dialogue_payload(payload)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].session_id, "7")


if __name__ == "__main__":
    unittest.main()
