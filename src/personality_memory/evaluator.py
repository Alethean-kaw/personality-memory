from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from .consolidator import MemoryConsolidator
from .extractor import MemoryExtractor
from .governance import MemoryGovernanceManager
from .persona_builder import PersonaBuilder
from .retrieval import RetrievalService
from .storage import SCHEMA_VERSION, Storage
from .utils import bundled_skill_root, copy_if_exists, latest_timestamp, stable_hash, utc_now


class ReplayEvaluator:
    def __init__(self, *, backend_name: str = "hybrid") -> None:
        self.backend_name = backend_name
        self.extractor = MemoryExtractor()
        self.governance = MemoryGovernanceManager()

    def run(self, manifest_path: Path, output_dir: Path | None = None) -> dict[str, Any]:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        temp_root = bundled_skill_root() / f".tmp-replay-{uuid.uuid4().hex}"
        temp_root.mkdir(parents=True, exist_ok=False)
        (temp_root / "skill.yaml").write_text("name: replay-eval\n", encoding="utf-8")
        try:
            self._seed_legacy_storage(temp_root, manifest, manifest_path.parent)
            report = self._run_manifest(manifest, manifest_path, temp_root)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

        output_dir = output_dir or (bundled_skill_root() / "exports" / "evals")
        output_dir.mkdir(parents=True, exist_ok=True)
        slug = self._slugify(manifest.get("name", manifest_path.stem))
        json_path = output_dir / f"{slug}-report.json"
        markdown_path = output_dir / f"{slug}-report.md"
        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        markdown_path.write_text(self._report_markdown(report), encoding="utf-8")
        report["json_path"] = str(json_path)
        report["markdown_path"] = str(markdown_path)
        return report

    def _seed_legacy_storage(self, temp_root: Path, manifest: dict[str, Any], base_dir: Path) -> None:
        seed_dir = manifest.get("legacy_seed_dir")
        if not seed_dir:
            return
        source_dir = self._resolve_path(seed_dir, base_dir)
        target_dir = temp_root / "data"
        target_dir.mkdir(parents=True, exist_ok=True)
        for child in source_dir.iterdir():
            if child.is_file():
                copy_if_exists(child, target_dir / child.name)

    def _ensure_storage(self, temp_root: Path, profile_id: str) -> Storage:
        try:
            return Storage(temp_root, profile_id)
        except ValueError:
            base_storage = Storage(temp_root)
            if base_storage.get_profile_metadata(profile_id) is None:
                base_storage.create_profile(profile_id, display_name=profile_id, backend=self.backend_name)
            return Storage(temp_root, profile_id)

    def _run_manifest(self, manifest: dict[str, Any], manifest_path: Path, temp_root: Path) -> dict[str, Any]:
        default_profile = manifest.get("profile", "default")
        storage = self._ensure_storage(temp_root, default_profile)
        dialogue_entries = manifest.get("dialogues", [])
        retrieval_checks = manifest.get("retrieval_checks", [])
        memory_checks = manifest.get("memory_checks", [])
        actions = manifest.get("actions", [])
        steps: list[dict[str, Any]] = []

        for index, entry in enumerate(dialogue_entries, start=1):
            dialogue_path, profile_id = self._resolve_dialogue_entry(entry, manifest_path.parent, default_profile)
            reference_time = self._process_dialogue(dialogue_path, temp_root, profile_id)
            executed_actions = [
                self._apply_action(action, temp_root, default_profile, reference_time)
                for action in actions
                if int(action.get("step", -1)) == index
            ]
            step_report = {
                "step": index,
                "profile": profile_id,
                "dialogue": str(dialogue_path),
                "counts": self._current_counts(temp_root, profile_id),
                "actions": executed_actions,
                "retrieval_checks": self._run_retrieval_checks(index, retrieval_checks, temp_root, default_profile, reference_time),
                "memory_checks": self._run_memory_checks(index, memory_checks, temp_root, default_profile),
                "invariants": self._run_invariants(temp_root, profile_id, default_profile, reference_time),
            }
            steps.append(step_report)

        passed = all(
            item.get("passed", True)
            for step in steps
            for group in (step["retrieval_checks"], step["memory_checks"], step["invariants"])
            for item in group
        )
        return {
            "name": manifest.get("name", manifest_path.stem),
            "backend": self.backend_name,
            "generated_at": utc_now(),
            "passed": passed,
            "steps": steps,
        }

    def _resolve_dialogue_entry(self, entry: Any, base_dir: Path, default_profile: str) -> tuple[Path, str]:
        if isinstance(entry, str):
            return self._resolve_path(entry, base_dir), default_profile
        if isinstance(entry, dict):
            return self._resolve_path(entry["path"], base_dir), entry.get("profile", default_profile)
        raise ValueError("Each dialogue entry must be a string path or an object with path/profile.")

    def _process_dialogue(self, dialogue_path: Path, temp_root: Path, profile_id: str) -> str:
        from .cli import normalize_dialogue_payload

        storage = self._ensure_storage(temp_root, profile_id)
        payload = json.loads(dialogue_path.read_text(encoding="utf-8"))
        events = normalize_dialogue_payload(payload)
        added_events = storage.append_conversation_events(events)
        existing_candidates = storage.load_memory_candidates()
        id_index = {candidate.id: candidate for candidate in existing_candidates}
        extracted = self.extractor.extract_from_events(added_events, existing_candidates=existing_candidates)
        for candidate in extracted:
            id_index[candidate.id] = candidate
        storage.save_memory_candidates(sorted(id_index.values(), key=lambda item: (item.created_at, item.id)))

        candidates = self.extractor.extract_from_events(
            storage.load_conversation_events(),
            existing_candidates=storage.load_memory_candidates(),
        )
        storage.save_memory_candidates(candidates)
        reference_time = max((event.occurred_at for event in storage.load_conversation_events()), default=utc_now())
        profile = storage.get_profile_metadata(profile_id)
        consolidator = MemoryConsolidator(backend_name=profile.backend or self.backend_name, aging_policy=profile.aging_policy)
        result = consolidator.consolidate(
            storage.load_memory_candidates(),
            storage.load_long_term_memory(),
            storage.load_review_items(),
            reference_time=reference_time,
        )
        storage.save_memory_candidates(result.candidates)
        storage.save_long_term_memory(result.memories)
        storage.save_review_items(result.review_items)
        if result.revisions:
            storage.append_revisions(result.revisions)

        memories = storage.load_long_term_memory()
        builder = PersonaBuilder(aging_policy=profile.aging_policy)
        persona = builder.build(memories, reference_time=reference_time)
        storage.save_long_term_memory(memories)
        storage.save_persona_profile(persona)
        return reference_time

    def _apply_action(self, action: dict[str, Any], temp_root: Path, default_profile: str, reference_time: str) -> dict[str, Any]:
        profile_id = action.get("profile", default_profile)
        storage = self._ensure_storage(temp_root, profile_id)
        candidates = storage.load_memory_candidates()
        memories = storage.load_long_term_memory()
        review_items = storage.load_review_items()
        action_type = action.get("type")

        if action_type == "resolve_review":
            review_id = action.get("review_id") or self._match_review_id(action, candidates, review_items)
            result = self.governance.resolve_review(
                review_id=review_id,
                action=action["action"],
                reason=action["reason"],
                candidates=candidates,
                memories=memories,
                review_items=review_items,
                memory_id=action.get("memory_id"),
            )
            summary = f"Resolved {review_id} with {action['action']}"
        elif action_type == "reopen_candidate":
            candidate_id = action.get("candidate_id") or self._match_candidate_id(action, candidates)
            result = self.governance.reopen_candidate(
                candidate_id=candidate_id,
                reason=action["reason"],
                candidates=candidates,
                review_items=review_items,
                memories=memories,
            )
            summary = f"Reopened {candidate_id}"
        else:
            raise ValueError(f"Unsupported replay action type: {action_type}")

        storage.save_memory_candidates(result.candidates)
        storage.save_long_term_memory(result.memories)
        storage.save_review_items(result.review_items)
        if result.revisions:
            storage.append_revisions(result.revisions)
        persona = PersonaBuilder(aging_policy=storage.get_profile_metadata().aging_policy).build(result.memories, reference_time=reference_time)
        storage.save_long_term_memory(result.memories)
        storage.save_persona_profile(persona)
        return {"type": action_type, "summary": summary, "passed": True, "profile": profile_id}

    def _run_retrieval_checks(
        self,
        step: int,
        checks: list[dict[str, Any]],
        temp_root: Path,
        default_profile: str,
        reference_time: str,
    ) -> list[dict[str, Any]]:
        report: list[dict[str, Any]] = []
        for check in checks:
            if int(check.get("step", -1)) != step:
                continue
            profile_id = check.get("profile", default_profile)
            storage = self._ensure_storage(temp_root, profile_id)
            profile = storage.get_profile_metadata(profile_id)
            memories = storage.load_long_term_memory()
            result = RetrievalService(backend_name=profile.backend or self.backend_name, aging_policy=profile.aging_policy).retrieve(
                query=check["query"],
                memories=memories,
                review_items=storage.load_review_items(),
                profile_id=profile_id,
                top_k=int(check.get("top_k", 5)),
                include_contested=True,
                include_review=True,
                reference_time=reference_time,
            )
            hit_ids = [hit.memory_id for hit in result.memory_hits]
            expected = list(check.get("expect_memory_ids", []))
            absent = list(check.get("expect_absent_memory_ids", []))
            schema_ok = result.schema_version == SCHEMA_VERSION and result.profile_id == profile_id
            passed = schema_ok and all(item in hit_ids for item in expected) and all(item not in hit_ids for item in absent)
            report.append(
                {
                    "name": f"retrieval:{check['query']}",
                    "profile": profile_id,
                    "passed": passed,
                    "actual_memory_ids": hit_ids,
                    "expected_memory_ids": expected,
                    "expected_absent_memory_ids": absent,
                    "schema_version": result.schema_version,
                }
            )
        return report

    def _run_memory_checks(self, step: int, checks: list[dict[str, Any]], temp_root: Path, default_profile: str) -> list[dict[str, Any]]:
        report: list[dict[str, Any]] = []
        for check in checks:
            if int(check.get("step", -1)) != step:
                continue
            profile_id = check.get("profile", default_profile)
            storage = self._ensure_storage(temp_root, profile_id)
            memories = storage.load_long_term_memory()
            review_items = storage.load_review_items()
            candidates = storage.load_memory_candidates()
            active_ids = {memory.id for memory in memories if memory.active}
            inactive_ids = {memory.id for memory in memories if not memory.active}
            open_review_ids = {item.id for item in review_items if item.status == "open"}
            candidate_statuses = {candidate.id: candidate.status for candidate in candidates}
            lifecycle_states = {memory.id: memory.lifecycle_state for memory in memories}
            expected_active = set(check.get("active_memory_ids", []))
            expected_inactive = set(check.get("inactive_memory_ids", []))
            expected_open_reviews = set(check.get("open_review_ids", []))
            expected_candidate_statuses = dict(check.get("candidate_statuses", {}))
            expected_lifecycle_states = dict(check.get("lifecycle_states", {}))
            passed = (
                expected_active.issubset(active_ids)
                and expected_inactive.issubset(inactive_ids)
                and expected_open_reviews.issubset(open_review_ids)
                and all(candidate_statuses.get(candidate_id) == status for candidate_id, status in expected_candidate_statuses.items())
                and all(lifecycle_states.get(memory_id) == state for memory_id, state in expected_lifecycle_states.items())
            )
            report.append(
                {
                    "name": f"memory-step-{step}",
                    "profile": profile_id,
                    "passed": passed,
                    "active_memory_ids": sorted(active_ids),
                    "inactive_memory_ids": sorted(inactive_ids),
                    "open_review_ids": sorted(open_review_ids),
                    "candidate_statuses": candidate_statuses,
                    "lifecycle_states": lifecycle_states,
                }
            )
        return report

    def _run_invariants(self, temp_root: Path, profile_id: str, default_profile: str, reference_time: str) -> list[dict[str, Any]]:
        storage = self._ensure_storage(temp_root, profile_id)
        memories = storage.load_long_term_memory()
        review_items = storage.load_review_items()
        candidates = storage.load_memory_candidates()
        return [
            self._check_idempotence(profile_id, candidates, memories, review_items, storage, reference_time),
            self._check_terminal_support_invariant(profile_id),
            self._check_inactive_not_retrieved(profile_id, storage, reference_time),
            self._check_contested_not_in_main_hits(profile_id, storage, reference_time),
            self._check_review_auditability(profile_id, candidates, memories, review_items),
            self._check_runtime_contract(profile_id, storage, reference_time),
        ]

    def _check_idempotence(self, profile_id: str, candidates: list[Any], memories: list[Any], review_items: list[Any], storage: Storage, reference_time: str) -> dict[str, Any]:
        fresh_candidates = [type(candidate).from_dict(candidate.to_dict()) for candidate in candidates]
        fresh_memories = [type(memory).from_dict(memory.to_dict()) for memory in memories]
        fresh_reviews = [type(item).from_dict(item.to_dict()) for item in review_items]
        consolidator = MemoryConsolidator(backend_name=storage.get_profile_metadata().backend, aging_policy=storage.get_profile_metadata().aging_policy)
        rerun = consolidator.consolidate(fresh_candidates, fresh_memories, fresh_reviews, reference_time=reference_time)
        passed = (
            [candidate.to_dict() for candidate in rerun.candidates] == [candidate.to_dict() for candidate in candidates]
            and [memory.to_dict() for memory in rerun.memories] == [memory.to_dict() for memory in memories]
            and [item.to_dict() for item in rerun.review_items] == [item.to_dict() for item in review_items]
        )
        return {"name": "idempotence", "profile": profile_id, "passed": passed}

    def _check_terminal_support_invariant(self, profile_id: str) -> dict[str, Any]:
        from .models import EvidenceRef, MemoryCandidate

        def ref(event_id: str) -> EvidenceRef:
            return EvidenceRef(
                conversation_event_id=event_id,
                session_id="eval",
                message_id=event_id,
                speaker="user",
                occurred_at="2026-03-01T09:00:00Z",
                excerpt="example",
            )

        synthetic = [
            MemoryCandidate(id="cand_old", content="prefers concise answers", type="style", confidence=0.68, source_refs=[ref("evt1")], created_at="2026-03-01T09:00:00Z", status="accepted"),
            MemoryCandidate(id="cand_new", content="prefers concise answers", type="style", confidence=0.66, source_refs=[ref("evt2")], created_at="2026-03-02T09:00:00Z"),
        ]
        result = MemoryConsolidator(backend_name=self.backend_name).consolidate(synthetic, [], [], reference_time="2026-03-02T09:00:00Z")
        passed = result.created == 0 and result.pending == 1 and result.candidates[1].status == "candidate"
        return {"name": "terminal_support_ignored", "profile": profile_id, "passed": passed}

    def _check_inactive_not_retrieved(self, profile_id: str, storage: Storage, reference_time: str) -> dict[str, Any]:
        memories = storage.load_long_term_memory()
        review_items = storage.load_review_items()
        passed = True
        checked_ids: list[str] = []
        service = RetrievalService(backend_name=storage.get_profile_metadata().backend, aging_policy=storage.get_profile_metadata().aging_policy)
        for memory in memories:
            if memory.active:
                continue
            checked_ids.append(memory.id)
            result = service.retrieve(query=memory.summary, memories=memories, review_items=review_items, profile_id=profile_id, reference_time=reference_time)
            if any(hit.memory_id == memory.id for hit in result.memory_hits):
                passed = False
        return {"name": "inactive_not_retrieved", "profile": profile_id, "passed": passed, "checked_memory_ids": checked_ids}

    def _check_contested_not_in_main_hits(self, profile_id: str, storage: Storage, reference_time: str) -> dict[str, Any]:
        memories = storage.load_long_term_memory()
        review_items = storage.load_review_items()
        passed = True
        checked_ids: list[str] = []
        service = RetrievalService(backend_name=storage.get_profile_metadata().backend, aging_policy=storage.get_profile_metadata().aging_policy)
        for memory in memories:
            if not memory.active or memory.contradiction_count < service.contested_threshold:
                continue
            checked_ids.append(memory.id)
            result = service.retrieve(query=memory.summary, memories=memories, review_items=review_items, profile_id=profile_id, reference_time=reference_time)
            in_hits = any(hit.memory_id == memory.id for hit in result.memory_hits)
            in_contested = any(signal.memory_id == memory.id for signal in result.contested_signals)
            if in_hits or not in_contested:
                passed = False
        return {"name": "contested_separated", "profile": profile_id, "passed": passed, "checked_memory_ids": checked_ids}

    def _check_review_auditability(self, profile_id: str, candidates: list[Any], memories: list[Any], review_items: list[Any]) -> dict[str, Any]:
        candidate_ids = {candidate.id for candidate in candidates}
        memory_ids = {memory.id for memory in memories}
        passed = True
        for item in review_items:
            if item.status != "open":
                continue
            if item.candidate_id not in candidate_ids:
                passed = False
            if item.target_memory_id is not None and item.target_memory_id not in memory_ids:
                passed = False
            if item.resolution_action is not None or item.resolved_at is not None:
                passed = False
        return {"name": "review_auditability", "profile": profile_id, "passed": passed}

    def _check_runtime_contract(self, profile_id: str, storage: Storage, reference_time: str) -> dict[str, Any]:
        result = RetrievalService(backend_name=storage.get_profile_metadata().backend, aging_policy=storage.get_profile_metadata().aging_policy).retrieve(
            query="runtime contract check",
            memories=storage.load_long_term_memory(),
            review_items=storage.load_review_items(),
            profile_id=profile_id,
            reference_time=reference_time,
        )
        required = {"schema_version", "profile_id", "query", "generated_at", "memory_hits", "persona_adaptation_notes", "contested_signals", "open_reviews", "usage_guidance", "memory_policy"}
        passed = required.issubset(result.to_dict()) and result.profile_id == profile_id and result.schema_version == SCHEMA_VERSION
        return {"name": "runtime_contract", "profile": profile_id, "passed": passed}

    def _current_counts(self, temp_root: Path, profile_id: str) -> dict[str, int]:
        storage = self._ensure_storage(temp_root, profile_id)
        return {
            "conversation_events": len(storage.load_conversation_events()),
            "memory_candidates": len(storage.load_memory_candidates()),
            "long_term_memory": len(storage.load_long_term_memory()),
            "open_reviews": len([item for item in storage.load_review_items() if item.status == "open"]),
        }

    def _match_review_id(self, action: dict[str, Any], candidates: list[Any], review_items: list[Any]) -> str:
        candidate_id = action.get("candidate_id")
        if candidate_id is None and action.get("candidate_content"):
            candidate_id = self._match_candidate_id(action, candidates)
        for item in review_items:
            if item.status == "open" and item.candidate_id == candidate_id:
                return item.id
        raise ValueError("Could not resolve a matching open review item for the replay action.")

    def _match_candidate_id(self, action: dict[str, Any], candidates: list[Any]) -> str:
        if action.get("candidate_id"):
            return action["candidate_id"]
        candidate_content = action.get("candidate_content")
        for candidate in candidates:
            if candidate.content == candidate_content:
                return candidate.id
        raise ValueError("Could not resolve a candidate for the replay action.")

    def _resolve_path(self, value: str, base_dir: Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else (base_dir / path).resolve()

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
        return slug or f"eval-{stable_hash(value)}"

    def _report_markdown(self, report: dict[str, Any]) -> str:
        lines = [
            f"# Replay Eval: {report['name']}",
            "",
            f"- Backend: {report['backend']}",
            f"- Passed: {report['passed']}",
            f"- Generated at: {report['generated_at']}",
        ]
        for step in report["steps"]:
            lines.extend(["", f"## Step {step['step']}", f"- Profile: {step['profile']}", f"- Dialogue: {step['dialogue']}", f"- Counts: {step['counts']}"])
            for section_name in ("actions", "retrieval_checks", "memory_checks", "invariants"):
                items = step[section_name]
                if not items:
                    continue
                lines.append(f"### {section_name.replace('_', ' ').title()}")
                for item in items:
                    label = item.get("name", item.get("summary", section_name))
                    lines.append(f"- {label}: passed={item.get('passed', True)}")
        return "\n".join(lines)



