from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

SKILL_ROOT_MARKERS = ("skill.yaml", "SKILL.md")
PROJECT_MARKERS = SKILL_ROOT_MARKERS + ("pyproject.toml",)
TOKEN_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]+")
TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d",
)


def format_utc_timestamp(value: datetime) -> str:
    timestamp = value.astimezone(timezone.utc).replace(microsecond=0)
    return timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now() -> str:
    return format_utc_timestamp(datetime.now(timezone.utc))


def parse_timestamp(value: str) -> datetime:
    raw = value.strip()
    if not raw:
        raise ValueError("Timestamp must not be empty.")

    iso_candidate = raw[:-1] + "+00:00" if raw[-1:] in {"Z", "z"} else raw
    try:
        parsed = datetime.fromisoformat(iso_candidate)
    except ValueError:
        parsed = None

    if parsed is None:
        for timestamp_format in TIMESTAMP_FORMATS:
            try:
                parsed = datetime.strptime(raw, timestamp_format)
                break
            except ValueError:
                continue

    if parsed is None:
        raise ValueError(
            "Timestamp must be ISO 8601 / RFC3339 or one of: YYYY-MM-DD HH:MM[:SS], YYYY/MM/DD HH:MM[:SS], YYYY-MM-DD, YYYY/MM/DD."
        )

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def normalize_timestamp(value: str) -> str:
    return format_utc_timestamp(parse_timestamp(value))


def sort_timestamp(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parse_timestamp(value)


def latest_timestamp(*values: str) -> str:
    non_empty = [value for value in values if value]
    if not non_empty:
        return ""
    latest = max(parse_timestamp(value) for value in non_empty)
    return format_utc_timestamp(latest)


def shift_timestamp(value: str, *, days: int = 0) -> str:
    return format_utc_timestamp(parse_timestamp(value) + timedelta(days=days))


def days_between(later: str, earlier: str) -> float:
    return (parse_timestamp(later) - parse_timestamp(earlier)).total_seconds() / 86400.0


def _find_root(candidate: Path, markers: tuple[str, ...]) -> Path | None:
    current = candidate if candidate.is_dir() else candidate.parent
    for parent in (current, *current.parents):
        if all((parent / marker).exists() for marker in SKILL_ROOT_MARKERS):
            return parent
        if any((parent / marker).exists() for marker in markers):
            return parent
    return None


def bundled_skill_root() -> Path:
    package_root = _find_root(Path(__file__).resolve(), SKILL_ROOT_MARKERS)
    if package_root is not None:
        return package_root

    fallback = _find_root(Path(__file__).resolve(), PROJECT_MARKERS)
    if fallback is not None:
        return fallback
    raise RuntimeError("Could not resolve the bundled skill root from the installed package.")


def detect_project_root(start: Path | None = None) -> Path:
    if start is None:
        return bundled_skill_root()

    resolved = start.resolve()
    root = _find_root(resolved, SKILL_ROOT_MARKERS)
    if root is not None:
        return root

    raise ValueError(
        f"Could not resolve a skill root from {resolved}. Expected a directory containing skill markers like skill.yaml or SKILL.md."
    )


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def copy_if_exists(source: Path, destination: Path) -> bool:
    if not source.exists():
        return False
    ensure_directory(destination.parent)
    shutil.copy2(source, destination)
    return True


def stable_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def normalize_text(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(normalize_text(text))


def unique_preserve_order(values: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    result: list[Any] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def slugify_text(value: str, default: str = "profile") -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return slug or default


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return default
    return json.loads(raw)


def write_json(path: Path, payload: Any) -> None:
    ensure_directory(path.parent)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    ensure_directory(path.parent)
    serialized = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    if serialized:
        serialized += "\n"
    path.write_text(serialized, encoding="utf-8")


def sentence_excerpt(text: str, limit: int = 160) -> str:
    compact = re.sub(r"\s+", " ", text.strip())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def join_clauses(clauses: list[str]) -> str:
    cleaned = [clause.strip().rstrip(".") for clause in clauses if clause.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return ", ".join(cleaned[:-1]) + f", and {cleaned[-1]}"
