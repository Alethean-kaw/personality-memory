from __future__ import annotations

import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from personality_memory.utils import bundled_skill_root, detect_project_root  # noqa: E402


class RootResolutionTests(unittest.TestCase):
    def test_default_root_uses_bundled_skill_root(self) -> None:
        expected = bundled_skill_root()
        base = ROOT / f".tmp-root-default-{uuid.uuid4().hex}"
        other_repo = base / "other-repo"
        nested = other_repo / "subdir" / "deep"
        try:
            nested.mkdir(parents=True, exist_ok=False)
            (other_repo / "pyproject.toml").write_text("[project]\nname='other'\n", encoding="utf-8")

            original_cwd = Path.cwd()
            os.chdir(nested)
            try:
                self.assertEqual(detect_project_root(None), expected)
            finally:
                os.chdir(original_cwd)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_explicit_root_resolves_to_skill_marker_parent(self) -> None:
        base = ROOT / f".tmp-root-explicit-{uuid.uuid4().hex}"
        skill_root = base / "custom-skill"
        nested = skill_root / "workspace" / "nested"
        try:
            nested.mkdir(parents=True, exist_ok=False)
            (skill_root / "skill.yaml").write_text("name: custom-skill\n", encoding="utf-8")

            self.assertEqual(detect_project_root(nested), skill_root.resolve())
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_explicit_root_requires_skill_markers(self) -> None:
        invalid_path = Path(ROOT.anchor) / f"__codex-invalid-root-{uuid.uuid4().hex}" / "workspace"

        with self.assertRaisesRegex(ValueError, "Could not resolve a skill root"):
            detect_project_root(invalid_path)


if __name__ == "__main__":
    unittest.main()
