from __future__ import annotations

import re
from typing import Iterable

from .candidate_lifecycle import merge_candidate_evidence
from .models import ConversationEvent, EvidenceRef, MemoryCandidate
from .rules import EXTRACTION_PATTERNS, STABILITY_MARKERS, TASK_NOISE_MARKERS, TEMPORAL_NOISE_MARKERS
from .scoring import candidate_confidence
from .utils import latest_timestamp, normalize_text, sentence_excerpt, sort_timestamp, stable_hash, tokenize


class MemoryExtractor:
    def __init__(self, minimum_confidence: float = 0.46) -> None:
        self.minimum_confidence = minimum_confidence

    def extract_from_events(
        self,
        events: Iterable[ConversationEvent],
        existing_candidates: Iterable[MemoryCandidate] | None = None,
        archived_candidates: Iterable[MemoryCandidate] | None = None,
    ) -> list[MemoryCandidate]:
        active_candidates = [candidate for candidate in existing_candidates or [] if candidate.lifecycle_state != "archived"]
        preserved_by_key = {(candidate.type, candidate.content): candidate for candidate in active_candidates}
        archived_by_key = {(candidate.type, candidate.content): candidate for candidate in archived_candidates or []}
        extracted: dict[tuple[str, str], MemoryCandidate] = {}

        for event in events:
            if normalize_text(event.speaker) not in {"user", "human"}:
                continue
            for candidate in self.extract_from_event(event):
                key = (candidate.type, candidate.content)
                archived = archived_by_key.get(key)
                if archived is not None and self._is_historical_for_archived_candidate(event.occurred_at, archived):
                    continue

                current = extracted.get(key)
                if current is None:
                    preserved = preserved_by_key.get(key)
                    current = MemoryCandidate.from_dict(preserved.to_dict()) if preserved is not None else candidate
                    extracted[key] = current
                    if preserved is None:
                        current.last_seen = candidate.created_at
                        current.reinforcement_count = max(1, len(current.source_refs))
                    else:
                        self._merge_candidate_signal(current, candidate)
                        continue
                else:
                    self._merge_candidate_signal(current, candidate)

        values = sorted(extracted.values(), key=lambda item: (sort_timestamp(item.created_at), item.id))
        for candidate in values:
            candidate.reinforcement_count = max(1, len(candidate.source_refs), candidate.reinforcement_count)
            if not candidate.last_seen:
                candidate.last_seen = candidate.created_at
        return values

    def extract_from_event(self, event: ConversationEvent) -> list[MemoryCandidate]:
        source_text = normalize_text(event.text)
        if not source_text:
            return []

        candidates: list[MemoryCandidate] = []
        for pattern in EXTRACTION_PATTERNS:
            for match in pattern.regex.finditer(event.text):
                fragment = self._clean_fragment(match.group("value"))
                if not fragment:
                    continue
                if self._looks_like_noise(fragment, source_text):
                    continue
                content = self._canonicalize(pattern.canonical_prefix, fragment)
                confidence = candidate_confidence(
                    base_confidence=pattern.base_confidence,
                    has_stability_marker=self._has_any(source_text, STABILITY_MARKERS),
                    has_temporal_noise=self._has_any(source_text, TEMPORAL_NOISE_MARKERS),
                    fragment_length=len(tokenize(fragment)),
                    source_text=source_text,
                )
                if confidence < self.minimum_confidence:
                    continue
                candidate_id = self._candidate_id(pattern.candidate_type, content, event.id)
                candidates.append(
                    MemoryCandidate(
                        id=candidate_id,
                        content=content,
                        type=pattern.candidate_type,
                        confidence=confidence,
                        source_refs=[
                            EvidenceRef(
                                conversation_event_id=event.id,
                                session_id=event.session_id,
                                message_id=event.message_id,
                                speaker=event.speaker,
                                occurred_at=event.occurred_at,
                                excerpt=sentence_excerpt(event.text),
                            )
                        ],
                        created_at=event.occurred_at,
                        last_seen=event.occurred_at,
                        reinforcement_count=1,
                    )
                )
        return self._deduplicate_candidates(candidates)

    def _merge_candidate_signal(self, current: MemoryCandidate, candidate: MemoryCandidate) -> None:
        current.source_refs = merge_candidate_evidence(current.source_refs, candidate.source_refs)
        current.confidence = max(current.confidence, candidate.confidence)
        current.created_at = current.created_at or candidate.created_at
        current.last_seen = latest_timestamp(current.last_seen, candidate.last_seen, candidate.created_at)
        current.reinforcement_count = max(current.reinforcement_count, len(current.source_refs))
        if current.status == "candidate" and current.lifecycle_state == "cooling":
            current.lifecycle_state = "active"
            current.decay_score = 0.0
        if current.status == "outdated" and current.lifecycle_state != "archived":
            current.status = "candidate"
            current.archive_reason = None
            current.archived_at = None

    def _is_historical_for_archived_candidate(self, occurred_at: str, archived_candidate: MemoryCandidate) -> bool:
        anchor = archived_candidate.archived_at or archived_candidate.last_seen or archived_candidate.created_at
        if not anchor:
            return False
        return sort_timestamp(occurred_at) <= sort_timestamp(anchor)

    def _clean_fragment(self, fragment: str) -> str:
        fragment = fragment.strip().strip("\"'`")
        fragment = re.split(r"(?:,|;)?\s+(?:and|but)\s+i\s+\b", fragment, maxsplit=1, flags=re.IGNORECASE)[0]
        fragment = re.split(r"(?:,|;)?\s*(?:而且|但是|并且)\s*我", fragment, maxsplit=1)[0]
        fragment = re.sub(r"^(?:that is|that are|to|for)\s+", "", fragment, flags=re.IGNORECASE)
        fragment = re.sub(r"^(?:the|a|an)\s+", "", fragment, flags=re.IGNORECASE)
        fragment = re.sub(r"\s+", " ", fragment)
        fragment = fragment.strip(" .,!?:;，。！？；")
        return fragment

    def _looks_like_noise(self, fragment: str, source_text: str) -> bool:
        lowered_fragment = normalize_text(fragment)
        if len(tokenize(fragment)) < 2:
            return True
        if self._has_any(lowered_fragment, TEMPORAL_NOISE_MARKERS):
            return True
        if self._has_any(lowered_fragment, TASK_NOISE_MARKERS):
            return True
        if lowered_fragment.startswith(("help me ", "show me ", "write ", "fix ")):
            return True
        if "?" in fragment:
            return True
        if normalize_text(source_text).startswith(("can you", "could you", "would you")) and "i " not in normalize_text(source_text):
            return True
        return False

    def _canonicalize(self, prefix: str, fragment: str) -> str:
        return f"{prefix} {normalize_text(fragment)}"

    def _candidate_id(self, candidate_type: str, content: str, seed: str) -> str:
        return f"cand_{stable_hash(f'{candidate_type}|{content}|{seed}') }"

    def _deduplicate_candidates(self, candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
        deduped: dict[tuple[str, str], MemoryCandidate] = {}
        for candidate in candidates:
            key = (candidate.type, candidate.content)
            current = deduped.get(key)
            if current is None or candidate.confidence > current.confidence:
                deduped[key] = candidate
        return list(deduped.values())

    def _has_any(self, text: str, markers: set[str]) -> bool:
        return any(marker in text for marker in markers)
