from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from personality_memory.runtime import SessionRuntime  # noqa: E402
from personality_memory.storage import Storage  # noqa: E402


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / f".tmp-runtime-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=False)
        (self.root / "skill.yaml").write_text("name: runtime-test\n", encoding="utf-8")
        self.runtime = SessionRuntime(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def request(self, action: str, params: dict[str, object] | None = None, request_id: str = "req") -> dict[str, object]:
        payload = {"id": request_id, "action": action, "params": params or {}}
        return self.runtime.handle_line(json.dumps(payload, ensure_ascii=False))

    def load_messages(self, name: str) -> list[dict[str, object]]:
        payload = json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))
        return payload["messages"]

    def test_hello_and_open_session_support_binding(self) -> None:
        hello = self.request("hello", request_id="hello-1")
        self.assertTrue(hello["ok"])
        self.assertIn("step", hello["result"]["supported_actions"])
        self.assertIn("export", hello["result"]["supported_actions"])

        created = self.request("create_profile", {"profile_id": "alpha", "display_name": "Alpha"}, request_id="create-1")
        self.assertTrue(created["ok"])
        self.assertEqual(created["result"]["profile"]["id"], "alpha")

        opened = self.request("open_session", {"session_id": "thread-1", "profile_id": "alpha"}, request_id="open-1")
        self.assertTrue(opened["ok"])
        self.assertEqual(opened["result"]["binding_source"], "explicit")
        self.assertEqual(opened["result"]["profile_id"], "alpha")

        reopened = self.request("open_session", {"session_id": "thread-1"}, request_id="open-2")
        self.assertTrue(reopened["ok"])
        self.assertEqual(reopened["result"]["binding_source"], "existing_binding")
        self.assertEqual(reopened["result"]["profile_id"], "alpha")

    def test_step_persists_then_retrieves_and_reuses_session_binding(self) -> None:
        self.request("create_profile", {"profile_id": "alpha"}, request_id="create-alpha")
        messages = self.load_messages("dialogue_01.json")

        first = self.request(
            "step",
            {"session_id": "thread-step", "profile_id": "alpha", "query": "How should I answer?", "messages": messages, "top_k": 3},
            request_id="step-1",
        )
        self.assertTrue(first["ok"])
        self.assertEqual(first["result"]["session"]["binding_source"], "explicit")
        self.assertGreater(first["result"]["write_summary"]["events_added"], 0)
        self.assertEqual(first["result"]["context"]["profile_id"], "alpha")
        self.assertIn("Persona Profile", first["result"]["persona_snapshot"]["markdown_summary"])

        second = self.request(
            "step",
            {"session_id": "thread-step", "query": "How should I answer?", "messages": messages, "top_k": 3},
            request_id="step-2",
        )
        self.assertTrue(second["ok"])
        self.assertEqual(second["result"]["session"]["binding_source"], "existing_binding")
        self.assertEqual(second["result"]["write_summary"]["events_added"], 0)

        binding = Storage(self.root).get_runtime_session_binding("thread-step")
        self.assertIsNotNone(binding)
        self.assertEqual(binding.profile_id, "alpha")
        self.assertEqual(binding.last_action, "step")

    def test_conflict_review_can_be_resolved_via_runtime_actions(self) -> None:
        base_messages = self.load_messages("dialogue_01.json")
        conflict_messages = self.load_messages("dialogue_03_conflict.json")

        self.request("step", {"session_id": "thread-conflict", "query": "How should I answer?", "messages": base_messages}, request_id="base-step")
        conflicted = self.request("step", {"session_id": "thread-conflict", "query": "How should I answer now?", "messages": conflict_messages}, request_id="conflict-step")
        self.assertTrue(conflicted["ok"])
        self.assertGreaterEqual(conflicted["result"]["write_summary"]["conflicts"], 1)
        self.assertTrue(conflicted["result"]["context"]["open_reviews"])

        review_id = conflicted["result"]["context"]["open_reviews"][0]["id"]
        resolved = self.request(
            "resolve_review",
            {"session_id": "thread-conflict", "review_id": review_id, "action": "reject-candidate", "reason": "Keep concise preference as the stable one."},
            request_id="resolve-review",
        )
        self.assertTrue(resolved["ok"])

        shown = self.request("show_review", {"session_id": "thread-conflict", "review_id": review_id}, request_id="show-review")
        self.assertTrue(shown["ok"])
        self.assertEqual(shown["result"]["review_item"]["status"], "resolved")
        self.assertEqual(shown["result"]["review_item"]["resolution_action"], "reject-candidate")

    def test_subprocess_runtime_jsonl_roundtrip_and_binding_persists(self) -> None:
        proc = self.start_runtime_process()
        try:
            hello = self.send_subprocess_request(proc, {"id": "1", "action": "hello", "params": {}})
            self.assertTrue(hello["ok"])

            created = self.send_subprocess_request(proc, {"id": "2", "action": "create_profile", "params": {"profile_id": "alpha"}})
            self.assertTrue(created["ok"])

            opened = self.send_subprocess_request(proc, {"id": "3", "action": "open_session", "params": {"session_id": "proc-thread", "profile_id": "alpha"}})
            self.assertTrue(opened["ok"])
            self.assertEqual(opened["result"]["binding_source"], "explicit")

            step = self.send_subprocess_request(
                proc,
                {"id": "4", "action": "step", "params": {"session_id": "proc-thread", "query": "How should I answer?", "messages": self.load_messages("dialogue_01.json")}},
            )
            self.assertTrue(step["ok"])
            self.assertEqual(step["result"]["session"]["profile_id"], "alpha")

            retrieved = self.send_subprocess_request(proc, {"id": "5", "action": "retrieve_context", "params": {"session_id": "proc-thread", "query": "json and concise"}})
            self.assertTrue(retrieved["ok"])
            self.assertEqual(retrieved["result"]["profile_id"], "alpha")

            exported = self.send_subprocess_request(proc, {"id": "6", "action": "export", "params": {"session_id": "proc-thread", "write_files": True, "output_dir": str(self.root / "exports-sub")}})
            self.assertTrue(exported["ok"])
            self.assertTrue(Path(exported["result"]["json_path"]).exists())
            self.assertTrue(Path(exported["result"]["markdown_path"]).exists())

            closed = self.send_subprocess_request(proc, {"id": "7", "action": "close_session", "params": {"session_id": "proc-thread"}})
            self.assertTrue(closed["ok"])
            self.assertIsNotNone(closed["result"]["closed_at"])
        finally:
            self.stop_runtime_process(proc)

        proc2 = self.start_runtime_process()
        try:
            reopened = self.send_subprocess_request(proc2, {"id": "8", "action": "open_session", "params": {"session_id": "proc-thread"}})
            self.assertTrue(reopened["ok"])
            self.assertEqual(reopened["result"]["binding_source"], "existing_binding")
            self.assertEqual(reopened["result"]["profile_id"], "alpha")
        finally:
            self.stop_runtime_process(proc2)

    def start_runtime_process(self) -> subprocess.Popen[str]:
        env = os.environ.copy()
        python_path = str(ROOT / "src")
        env["PYTHONPATH"] = python_path if not env.get("PYTHONPATH") else python_path + os.pathsep + env["PYTHONPATH"]
        return subprocess.Popen(
            [sys.executable, "-u", "-m", "personality_memory", "--root", str(self.root), "session-runtime"],
            cwd=str(ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def send_subprocess_request(self, proc: subprocess.Popen[str], payload: dict[str, object]) -> dict[str, object]:
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            stderr = proc.stderr.read() if proc.stderr is not None else ""
            self.fail(f"Runtime subprocess returned no output. stderr={stderr}")
        return json.loads(line)

    def stop_runtime_process(self, proc: subprocess.Popen[str]) -> None:
        if proc.stdin is not None and not proc.stdin.closed:
            proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=5)
        for stream in (proc.stdout, proc.stderr):
            if stream is not None and not stream.closed:
                stream.close()


    def test_runtime_candidate_archive_and_health_actions(self) -> None:
        self.request("step", {"session_id": "thread-archive", "query": "How should I answer?", "messages": self.load_messages("dialogue_01.json")}, request_id="seed-step")

        listed = self.request("list_candidates", {"session_id": "thread-archive"}, request_id="list-candidates")
        self.assertTrue(listed["ok"])
        candidate_id = listed["result"]["active_candidates"][0]["id"]

        archived = self.request("archive_candidates", {"session_id": "thread-archive", "candidate_ids": [candidate_id], "reason": "Move terminal candidate out of the active working set."}, request_id="archive-candidate")
        self.assertTrue(archived["ok"])
        self.assertGreaterEqual(archived["result"]["archived"], 1)

        listed_archived = self.request("list_candidates", {"session_id": "thread-archive", "include_archived": True}, request_id="list-candidates-archived")
        self.assertTrue(listed_archived["ok"])
        self.assertTrue(any(item["id"] == candidate_id for item in listed_archived["result"]["archived_candidates"]))

        health = self.request("storage_health", {"session_id": "thread-archive"}, request_id="storage-health")
        self.assertTrue(health["ok"])
        self.assertTrue(health["result"]["ok"])


if __name__ == "__main__":
    unittest.main()

