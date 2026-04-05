from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from personality_memory.cli import main as cli_main  # noqa: E402
from personality_memory.storage import Storage  # noqa: E402


def run(command: list[str]) -> None:
    print(f"$ personality-memory {' '.join(command)}")
    cli_main(["--root", str(ROOT), *command])
    print()


def ensure_profile(root: Path, profile_id: str, display_name: str) -> None:
    storage = Storage(root)
    if storage.get_profile_metadata(profile_id) is None:
        storage.create_profile(profile_id, display_name=display_name)
    Storage(root, profile_id).reset()


def main() -> int:
    base = Storage(ROOT)
    Storage(ROOT, base.registry.default_profile_id).reset()
    ensure_profile(ROOT, "demo-alt", "Demo Alt")

    print(f"Prepared skill data under {base.data_dir}")
    print()

    run(["migrate-storage"])
    run(["list-profiles"])
    run(["show-profile"])

    run(["ingest", str(ROOT / "examples" / "dialogue_01.json")])
    run(["ingest", str(ROOT / "examples" / "dialogue_02.json")])
    run(["extract"])
    run(["consolidate"])
    run(["build-persona"])
    run(["show-memory"])
    run(["retrieve-context", "--query", "Need concise JSON guidance for the tabletop writing tool"])
    run(["prepare-context", "--query", "Need concise JSON guidance for the tabletop writing tool"])

    run(["--profile", "demo-alt", "ingest", str(ROOT / "examples" / "dialogue_02.json")])
    run(["--profile", "demo-alt", "extract"])
    run(["--profile", "demo-alt", "consolidate"])
    run(["show-profile", "demo-alt"])

    run(["replay-eval", str(ROOT / "examples" / "eval_stable.json")])
    run(["replay-eval", str(ROOT / "examples" / "eval_multi_profile.json")])
    run(["replay-eval", str(ROOT / "examples" / "eval_migration.json")])
    run(["replay-eval", str(ROOT / "examples" / "eval_aging.json")])
    run(["export", "--all-profiles"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
