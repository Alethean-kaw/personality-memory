from __future__ import annotations

import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from personality_memory.models import ConversationEvent, EvidenceRef, LongTermMemory, MemoryCandidate  # noqa: E402
from personality_memory.storage import DEFAULT_PROFILE_ID, SCHEMA_VERSION, Storage  # noqa: E402


class StorageMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / f".tmp-storage-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=False)
        (self.root / "skill.yaml").write_text("name: storage-test\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _write_legacy_layout(self) -> None:
        data_dir = self.root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        event = {
            "id": "evt_legacy",
            "session_id": "legacy-session",
            "message_id": "m1",
            "speaker": "user",
            "text": "I prefer local-only tooling.",
            "occurred_at": "2026-02-25T09:00:00Z",
        }
        memory = {
            "id": "ltm_legacy",
            "summary": "prefers local-only tooling",
            "category": "preference",
            "evidence": [
                {
                    "conversation_event_id": "evt_legacy",
                    "session_id": "legacy-session",
                    "message_id": "m1",
                    "speaker": "user",
                    "occurred_at": "2026-02-25T09:00:00Z",
                    "excerpt": "I prefer local-only tooling.",
                }
            ],
            "confidence": 0.9,
            "first_seen": "2026-02-25T09:00:00Z",
            "last_seen": "2026-02-25T09:00:00Z",
            "reinforcement_count": 1,
            "contradiction_count": 0,
            "mutable": True,
            "active": True,
        }
        (data_dir / "conversations.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
        (data_dir / "memory_candidates.json").write_text("[]\n", encoding="utf-8")
        (data_dir / "long_term_memory.json").write_text(json.dumps([memory], indent=2), encoding="utf-8")
        (data_dir / "persona_profile.json").write_text("{}\n", encoding="utf-8")
        (data_dir / "review_items.json").write_text("[]\n", encoding="utf-8")
        (data_dir / "revisions.json").write_text("[]\n", encoding="utf-8")

    def test_migrates_flat_storage_into_default_profile_and_creates_backup(self) -> None:
        self._write_legacy_layout()

        storage = Storage(self.root)

        self.assertEqual(storage.profile_id, DEFAULT_PROFILE_ID)
        self.assertEqual(storage.registry.schema_version, SCHEMA_VERSION)
        self.assertTrue((self.root / "data" / "profiles" / DEFAULT_PROFILE_ID / "long_term_memory.json").exists())
        self.assertTrue((self.root / "data" / "legacy_backup" / "v1-flat" / "long_term_memory.json").exists())
        self.assertFalse((self.root / "data" / "long_term_memory.json").exists())
        self.assertEqual(storage.load_long_term_memory()[0].id, "ltm_legacy")
        self.assertEqual(len(storage.load_migrations()), 1)
        self.assertEqual(storage.load_migrations()[0].name, "flat-data-to-profiles")

    def test_migration_is_idempotent_when_storage_reopens(self) -> None:
        self._write_legacy_layout()

        Storage(self.root)
        reopened = Storage(self.root)

        self.assertEqual(len(reopened.load_migrations()), 1)
        self.assertEqual(reopened.load_long_term_memory()[0].id, "ltm_legacy")


class StorageProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / f".tmp-profiles-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=False)
        (self.root / "skill.yaml").write_text("name: profile-test\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_profiles_are_isolated_and_default_profile_can_change(self) -> None:
        storage = Storage(self.root)
        storage.create_profile("alpha", display_name="Alpha")
        storage.create_profile("beta", display_name="Beta")

        alpha_storage = Storage(self.root, "alpha")
        alpha_storage.append_conversation_events(
            [
                ConversationEvent(
                    id="evt_alpha",
                    session_id="alpha-session",
                    message_id="m1",
                    speaker="user",
                    text="I prefer local-only tooling.",
                    occurred_at="2026-03-01T09:00:00Z",
                )
            ]
        )
        alpha_storage.save_long_term_memory(
            [
                LongTermMemory(
                    id="ltm_alpha",
                    summary="prefers local-only tooling",
                    category="preference",
                    evidence=[
                        EvidenceRef(
                            conversation_event_id="evt_alpha",
                            session_id="alpha-session",
                            message_id="m1",
                            speaker="user",
                            occurred_at="2026-03-01T09:00:00Z",
                            excerpt="I prefer local-only tooling.",
                        )
                    ],
                    confidence=0.9,
                    first_seen="2026-03-01T09:00:00Z",
                    last_seen="2026-03-01T09:00:00Z",
                    reinforcement_count=1,
                    contradiction_count=0,
                    mutable=True,
                    active=True,
                )
            ]
        )

        beta_storage = Storage(self.root, "beta")
        self.assertEqual(beta_storage.load_conversation_events(), [])
        self.assertEqual(beta_storage.load_long_term_memory(), [])

        storage.set_default_profile("beta")
        default_storage = Storage(self.root)
        self.assertEqual(default_storage.profile_id, "beta")
        self.assertEqual(default_storage.get_profile_metadata().display_name, "Beta")

        snapshots = storage.export_all_profiles_state()
        self.assertIn("alpha", snapshots)
        self.assertIn("beta", snapshots)
        self.assertEqual(len(snapshots["alpha"]["conversation_events"]), 1)
        self.assertEqual(len(snapshots["beta"]["conversation_events"]), 0)


if __name__ == "__main__":
    unittest.main()

class StorageOperationalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / f".tmp-storage-ops-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=False)
        (self.root / "skill.yaml").write_text("name: storage-ops-test\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_profile_snapshot_can_restore_candidates(self) -> None:
        storage = Storage(self.root)
        candidate = MemoryCandidate(
            id="cand_snap",
            content="prefers local-only tooling",
            type="preference",
            confidence=0.8,
            created_at="2026-03-01T09:00:00Z",
        )

        with storage.mutation("seed-candidates", scope="profile"):
            storage.save_memory_candidates([candidate])

        with storage.mutation("clear-candidates", scope="profile"):
            storage.save_memory_candidates([])

        snapshots = storage.list_snapshots(scope="profile", profile_id="default")
        self.assertTrue(snapshots)
        snapshot_id = next(item["id"] for item in snapshots if item["action"] == "clear-candidates")

        with storage.mutation("restore-snapshot", scope="profile"):
            result = storage.restore_snapshot(snapshot_id, profile_id="default")

        self.assertEqual(result["snapshot_id"], snapshot_id)
        self.assertEqual(len(storage.load_memory_candidates()), 1)
        self.assertEqual(storage.load_memory_candidates()[0].id, "cand_snap")
        self.assertTrue(any(item.action == "restore_snapshot" for item in storage.load_revisions()))

    def test_storage_health_detects_active_archive_overlap(self) -> None:
        storage = Storage(self.root)
        candidate = MemoryCandidate(
            id="cand_overlap",
            content="prefers local-only tooling",
            type="preference",
            confidence=0.8,
            created_at="2026-03-01T09:00:00Z",
        )
        storage.save_memory_candidates([candidate])
        storage.save_candidate_archive([candidate])

        report = storage.storage_health()

        self.assertFalse(report["ok"])
        self.assertTrue(any("candidate_overlap:default" in issue for issue in report["issues"]))

