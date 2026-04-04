from __future__ import annotations

from typing import Callable

from .models import LongTermMemory, PersonaProfile, PersonaSection, PersonaSignal
from .rules import COMMUNICATION_HINTS, EMOTIONAL_HINTS, WORKFLOW_HINTS
from .scoring import signal_strength
from .utils import join_clauses, normalize_text, utc_now


class PersonaBuilder:
    def build(self, memories: list[LongTermMemory]) -> PersonaProfile:
        active_memories = [memory for memory in memories if memory.active]
        sorted_memories = sorted(active_memories, key=lambda item: (-item.confidence, -item.reinforcement_count, item.summary))

        communication = self._build_section(
            sorted_memories,
            lambda memory: memory.category in {"style", "preference", "taboo"} and self._contains_any(memory.summary, COMMUNICATION_HINTS | EMOTIONAL_HINTS),
            empty_message="Not enough evidence about communication preferences yet.",
        )
        priorities = self._build_section(
            sorted_memories,
            lambda memory: memory.category in {"worldview", "goal", "preference", "constraint"},
            empty_message="Not enough evidence about stable priorities yet.",
        )
        recurring = self._build_section(
            sorted_memories,
            lambda memory: memory.category in {"project", "routine"},
            empty_message="No recurring projects or interests are durable yet.",
        )
        working = self._build_section(
            sorted_memories,
            lambda memory: memory.category in {"project", "constraint", "preference", "routine", "style"} and self._contains_any(memory.summary, WORKFLOW_HINTS | COMMUNICATION_HINTS),
            empty_message="Not enough evidence about working preferences yet.",
        )
        emotional = self._build_section(
            sorted_memories,
            lambda memory: memory.category in {"style", "taboo", "preference"} and self._contains_any(memory.summary, EMOTIONAL_HINTS),
            empty_message="Not enough evidence about tone preferences yet.",
        )
        goals = self._build_section(
            sorted_memories,
            lambda memory: memory.category in {"goal", "project"},
            empty_message="No durable long-range goals are confirmed yet.",
        )
        avoidances = self._build_section(
            sorted_memories,
            lambda memory: memory.category in {"taboo", "constraint"} or memory.summary.startswith("avoids "),
            empty_message="No durable avoidances are confirmed yet.",
        )
        adaptation_notes = self._build_adaptation_notes(sorted_memories)
        markdown = self._to_markdown(
            communication,
            priorities,
            recurring,
            working,
            emotional,
            goals,
            avoidances,
            adaptation_notes,
        )

        return PersonaProfile(
            generated_at=utc_now(),
            memory_refs=[memory.id for memory in sorted_memories],
            communication_style=communication,
            priorities=priorities,
            recurring_interests=recurring,
            working_preferences=working,
            emotional_tone_preferences=emotional,
            likely_goals=goals,
            avoidances=avoidances,
            system_adaptation_notes=adaptation_notes,
            markdown_summary=markdown,
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
            signal = PersonaSignal(memory_id=memory.id, summary=memory.summary, confidence=memory.confidence)
            strength = signal_strength(memory.confidence)
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

    def _build_adaptation_notes(self, memories: list[LongTermMemory]) -> list[dict[str, object]]:
        notes: list[dict[str, object]] = []

        concise = [memory for memory in memories if any(token in normalize_text(memory.summary) for token in {"concise", "structured", "json", "direct"})]
        if concise:
            notes.append(
                self._make_note(
                    "Default to concise, structured answers and use JSON or explicit formats when it improves clarity.",
                    concise,
                )
            )

        local_cli = [memory for memory in memories if any(token in normalize_text(memory.summary) for token in {"local", "local-first", "cli", "terminal", "python", "file"})]
        if local_cli:
            notes.append(
                self._make_note(
                    "Prefer local-first, file-based, CLI-friendly solutions over hosted services or GUI-heavy ideas.",
                    local_cli,
                )
            )

        tone = [memory for memory in memories if any(token in normalize_text(memory.summary) for token in {"fluffy", "marketing", "patronizing", "hype", "warm", "friendly"})]
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
        strongest = max(memories, key=lambda memory: memory.confidence)
        return {
            "note": note,
            "memory_refs": [memory.id for memory in memories[:4]],
            "strength": signal_strength(strongest.confidence),
        }

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
            "## System Adaptation Notes",
        ]
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
