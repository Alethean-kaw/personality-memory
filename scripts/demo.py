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


def main() -> int:
    storage = Storage(ROOT)
    storage.reset()
    print(f"Reset data under {storage.paths.data_dir}")
    print()

    run(["ingest", str(ROOT / "examples" / "dialogue_01.json")])
    run(["ingest", str(ROOT / "examples" / "dialogue_02.json")])
    run(["extract"])
    run(["consolidate"])
    run(["show-memory"])
    run(["build-persona"])
    run(["show-persona"])
    run(["export"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
