from __future__ import annotations

from typing import Callable

from .lifecycle import DEFAULT_AGING_POLICY, apply_memory_lifecycle
from .models import LongTermMemory, PersonaProfile, PersonaSection, PersonaSignal
from .rules import COMMUNICATION_HINTS, EMOTIONAL_HINTS, WORKFLOW_HINTS
from .scoring import effective_persona_confidence, signal_strength
from .utils import join_clauses, normalize_text, utc_now


class PersonaBuilder:
    def __init__(self, contested_threshold: int = 2, aging_policy: str = DEFAULT_AGING_POLICY) -> None:
        self.contested_threshold = contested_threshold
        self.aging_policy = aging_policy

    def build(self, memories: list[LongTermMemory], *, reference_time: str | None = None) -> PersonaProfile:
        reference = reference_time or utc_now()
        for memory in memories:
            apply_memory_lifecycle(memory, reference_time=reference, aging_policy=self.aging_policy)

        active_memories = [memory for memory in memories if memory.active and memory.lifecycle_state == "active"]
        stable_memories = self._sort_memories(
            [memory for memory in active_memories if memory.contradiction_count < self.contested_threshold]
        )
        contested_memories = self._sort_memories(
            [memory for memory in active_memories if memory.contradiction_count >= self.contested_threshold]
        )

        communication = self._build_section(
            stable_memories,
            lambda memory: memory.category in {"style", "preference", "taboo"}
            and self._contains_any(memory.summary, COMMUNICATION_HINTS | EMOTIONAL_HINTS),
            empty_message="Not enough evidence about communication preferences yet.",
        )
        priorities = self._build_section(
            stable_memories,
            lambda memory: memory.category in {"worldview", "goal", "preference", "constraint"},
            empty_message="Not enough evidence about stable priorities yet.",
        )
        recurring = self._build_section(
            stable_memories,
            lambda memory: memory.category in {"project", "routine"},
            empty_message="No recurring projects or interests are durable yet.",
        )
        working = self._build_section(
            stable_memories,
            lambda memory: memory.category in {"project", "constraint", "preference", "routine", "style"}
            and self._contains_any(memory.summary, WORKFLOW_HINTS | COMMUNICATION_HINTS),
            empty_message="Not enough evidence about working preferences yet.",
        )
        emotional = self._build_section(
            stable_memories,
            lambda memory: memory.category in {"style", "taboo", "preference"}
            and self._contains_any(memory.summary, EMOTIONAL_HINTS),
            empty_message="Not enough evidence about tone preferences yet.",
        )
        goals = self._build_section(
            stable_memories,
            lambda memory: memory.category in {"goal", "project"},
            empty_message="No durable long-range goals are confirmed yet.",
        )
        avoidances = self._build_section(
            stable_memories,
            lambda memory: memory.category in {"taboo", "constraint"} or memory.summary.startswith("avoids "),
            empty_message="No durable avoidances are confirmed yet.",
        )
        contested_signals = self._build_contested_signals(contested_memories)
        adaptation_notes = self._build_adaptation_notes(stable_memories)
        markdown = self._to_markdown(
            communication,
            priorities,
            recurring,
            working,
            emotional,
            goals,
            avoidances,
            contested_signals,
            adaptation_notes,
        )

        return PersonaProfile(
            generated_at=reference,
            memory_refs=[memory.id for memory in [*stable_memories, *contested_memories]],
            communication_style=communication,
            priorities=priorities,
            recurring_interests=recurring,
            working_preferences=working,
            emotional_tone_preferences=emotional,
            likely_goals=goals,
            avoidances=avoidances,
            contested_signals=contested_signals,
            system_adaptation_notes=adaptation_notes,
            markdown_summary=markdown,
        )

    def _sort_memories(self, memories: list[LongTermMemory]) -> list[LongTermMemory]:
        return sorted(
            memories,
            key=lambda item: (-self._effective_confidence(item), -item.reinforcement_count, -item.confidence, item.summary),
        )

    def _build_section(
        self,
        memories: list[LongTermMemory],
        predicate: Callable[[LongTermMemory], bool],
        empty_message: str,
    ) -> PersonaSection:
        selected = [memory for memory in memories if predicate(memory)]
        if not selected:
            return PersonaSection(summary=empty_message)

        strong: list[PersonaSignal] = []
        medium: list[PersonaSignal] = []
        weak: list[PersonaSignal] = []
        for memory in selected[:6]:
            signal = self._build_signal(memory)
            strength = signal_strength(signal.effective_confidence if signal.effective_confidence is not None else signal.confidence)
            if strength == "strong":
                strong.append(signal)
            elif strength == "medium":
                medium.append(signal)
            else:
                weak.append(signal)

        section_summary = self._section_summary(selected[:4])
        return PersonaSection(
            summary=section_summary,
            strong_signals=strong,
            medium_signals=medium,
            weak_signals=weak,
        )

    def _build_contested_signals(self, memories: list[LongTermMemory]) -> list[PersonaSignal]:
        return [self._build_signal(memory) for memory in memories[:6]]

    def _build_adaptation_notes(self, memories: list[LongTermMemory]) -> list[dict[str, object]]:
        notes: list[dict[str, object]] = []

        concise = [
            memory
            for memory in memories
            if any(token in normalize_text(memory.summary) for token in {"concise", "structured", "json", "direct"})
        ]
        if concise:
            notes.append(
                self._make_note(
                    "Default to concise, structured answers and use JSON or explicit formats when it improves clarity.",
                    concise,
                )
            )

        local_cli = [
            memory
            for memory in memories
            if any(token in normalize_text(memory.summary) for token in {"local", "local-first", "cli", "terminal", "python", "file"})
        ]
        if local_cli:
            notes.append(
                self._make_note(
                    "Prefer local-first, file-based, CLI-friendly solutions over hosted services or GUI-heavy ideas.",
                    local_cli,
                )
            )

        tone = [
            memory
            for memory in memories
            if any(token in normalize_text(memory.summary) for token in {"fluffy", "marketing", "patronizing", "hype", "warm", "friendly"})
        ]
        if tone:
            notes.append(
                self._make_note(
                    "Avoid hype, fluffy marketing language, and patronizing tone; keep the interaction grounded and respectful.",
                    tone,
                )
            )

        projects = [memory for memory in memories if memory.category == "project"]
        if projects:
            notes.append(
                self._make_note(
                    "Maintain continuity around recurring projects and connect new advice back to the existing project context.",
                    projects,
                )
            )

        return notes

    def _make_note(self, note: str, memories: list[LongTermMemory]) -> dict[str, object]:
        strongest = max(memories, key=lambda memory: (self._effective_confidence(memory), memory.confidence))
        return {
            "note": note,
            "memory_refs": [memory.id for memory in memories[:4]],
            "strength": signal_strength(self._effective_confidence(strongest)),
        }

    def _build_signal(self, memory: LongTermMemory) -> PersonaSignal:
        return PersonaSignal(
            memory_id=memory.id,
            summary=memory.summary,
            confidence=memory.confidence,
            effective_confidence=self._effective_confidence(memory),
            contradiction_count=memory.contradiction_count,
        )

    def _effective_confidence(self, memory: LongTermMemory) -> float:
        return effective_persona_confidence(memory.confidence, memory.contradiction_count)

    def _section_summary(self, memories: list[LongTermMemory]) -> str:
        clauses = [memory.summary for memory in memories]
        return f"Signals suggest the user {join_clauses(clauses)}."

    def _to_markdown(
        self,
        communication: PersonaSection,
        priorities: PersonaSection,
        recurring: PersonaSection,
        working: PersonaSection,
        emotional: PersonaSection,
        goals: PersonaSection,
        avoidances: PersonaSection,
        contested_signals: list[PersonaSignal],
        adaptation_notes: list[dict[str, object]],
    ) -> str:
        lines = [
            "# Persona Profile",
            "",
            "## Communication Style",
            f"- {communication.summary}",
            "",
            "## Priorities",
            f"- {priorities.summary}",
            "",
            "## Recurring Interests",
            f"- {recurring.summary}",
            "",
            "## Working Preferences",
            f"- {working.summary}",
            "",
            "## Emotional Tone Preferences",
            f"- {emotional.summary}",
            "",
            "## Likely Goals",
            f"- {goals.summary}",
            "",
            "## Avoidances",
            f"- {avoidances.summary}",
            "",
            "## Contested Signals",
        ]
        if contested_signals:
            for signal in contested_signals:
                effective = signal.effective_confidence if signal.effective_confidence is not None else signal.confidence
                lines.append(
                    f"- {signal.summary} (id: {signal.memory_id}, confidence={signal.confidence:.2f}, effective_confidence={effective:.2f}, contradictions={signal.contradiction_count})"
                )
        else:
            lines.append("- No heavily contested memories right now.")

        lines.extend(["", "## System Adaptation Notes"])
        if adaptation_notes:
            for note in adaptation_notes:
                refs = ", ".join(note["memory_refs"])
                lines.append(f"- {note['note']} (refs: {refs})")
        else:
            lines.append("- No actionable adaptation notes yet.")
        return "\n".join(lines)

    def _contains_any(self, text: str, markers: set[str]) -> bool:
        lowered = normalize_text(text)
        return any(marker in lowered for marker in markers)
