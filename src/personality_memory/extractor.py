from __future__ import annotations

import re
from typing import Iterable

from .models import ConversationEvent, EvidenceRef, MemoryCandidate
from .rules import EXTRACTION_PATTERNS, STABILITY_MARKERS, TASK_NOISE_MARKERS, TEMPORAL_NOISE_MARKERS
from .scoring import candidate_confidence
from .utils import normalize_text, sentence_excerpt, stable_hash, tokenize


class MemoryExtractor:
    def __init__(self, minimum_confidence: float = 0.46) -> None:
        self.minimum_confidence = minimum_confidence

    def extract_from_events(
        self,
        events: Iterable[ConversationEvent],
        existing_candidates: Iterable[MemoryCandidate] | None = None,
    ) -> list[MemoryCandidate]:
        preserved = {candidate.id: candidate for candidate in existing_candidates or []}
        extracted: list[MemoryCandidate] = []
        seen_ids: set[str] = set()

        for event in events:
            if normalize_text(event.speaker) not in {"user", "human"}:
                continue
            for candidate in self.extract_from_event(event):
                if candidate.id in seen_ids:
                    continue
                if candidate.id in preserved:
                    old = preserved[candidate.id]
                    candidate.status = old.status
                    candidate.notes = old.notes
                    candidate.resolution_kind = old.resolution_kind
                    candidate.resolved_at = old.resolved_at
                    candidate.resolved_memory_id = old.resolved_memory_id
                seen_ids.add(candidate.id)
                extracted.append(candidate)
        return extracted

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
                candidate_id = self._candidate_id(event, pattern.candidate_type, content)
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
                    )
                )
        return self._deduplicate_candidates(candidates)

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

    def _candidate_id(self, event: ConversationEvent, candidate_type: str, content: str) -> str:
        return f"cand_{stable_hash(f'{event.id}|{candidate_type}|{content}')}"

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
