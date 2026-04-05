from __future__ import annotations

import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from personality_memory.evaluator import ReplayEvaluator  # noqa: E402


class ReplayEvaluatorTests(unittest.TestCase):
    def run_manifest(self, name: str) -> dict[str, object]:
        evaluator = ReplayEvaluator()
        output_dir = ROOT / f".tmp-eval-out-{uuid.uuid4().hex}"
        try:
            report = evaluator.run(ROOT / "examples" / name, output_dir=output_dir)
            self.assertTrue(Path(report["json_path"]).exists())
            self.assertTrue(Path(report["markdown_path"]).exists())
            saved = json.loads(Path(report["json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(saved["passed"], report["passed"])
            return report
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_stable_manifest_runs_and_writes_reports(self) -> None:
        report = self.run_manifest("eval_stable.json")
        self.assertTrue(report["passed"])
        self.assertEqual(len(report["steps"]), 2)
        self.assertTrue(all(item.get("passed", True) for step in report["steps"] for item in step["invariants"]))

    def test_conflict_manifest_runs_review_resolution_flow(self) -> None:
        report = self.run_manifest("eval_conflict.json")
        self.assertTrue(report["passed"])
        self.assertEqual(len(report["steps"]), 2)
        final_step = report["steps"][-1]
        self.assertEqual(final_step["actions"][0]["type"], "resolve_review")
        self.assertTrue(final_step["actions"][0]["passed"])
        self.assertTrue(all(item.get("passed", True) for item in final_step["memory_checks"]))

    def test_multi_profile_manifest_keeps_profiles_isolated(self) -> None:
        report = self.run_manifest("eval_multi_profile.json")
        self.assertTrue(report["passed"])
        profiles = {step["profile"] for step in report["steps"]}
        self.assertEqual(profiles, {"alpha", "beta"})

    def test_migration_manifest_uses_legacy_seed(self) -> None:
        report = self.run_manifest("eval_migration.json")
        self.assertTrue(report["passed"])
        self.assertEqual(report["steps"][0]["retrieval_checks"][0]["expected_memory_ids"], ["ltm_seed_local"])

    def test_aging_manifest_expires_and_revives_memory(self) -> None:
        report = self.run_manifest("eval_aging.json")
        self.assertTrue(report["passed"])
        self.assertEqual(len(report["steps"]), 3)
        self.assertTrue(any(item["name"] == "memory-step-2" and item["passed"] for item in report["steps"][1]["memory_checks"]))
        self.assertTrue(any(item["name"] == "memory-step-3" and item["passed"] for item in report["steps"][2]["memory_checks"]))


if __name__ == "__main__":
    unittest.main()
