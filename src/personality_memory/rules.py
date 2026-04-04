from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern


@dataclass(frozen=True, slots=True)
class ExtractionPattern:
    name: str
    regex: Pattern[str]
    candidate_type: str
    base_confidence: float
    canonical_prefix: str


TEMPORAL_NOISE_MARKERS = {
    "today",
    "tomorrow",
    "right now",
    "for now",
    "this week",
    "this month",
    "this afternoon",
    "temporarily",
    "temporary",
    "urgent",
    "one-off",
    "once",
    "今天",
    "临时",
    "暂时",
    "这周",
    "现在",
}

TASK_NOISE_MARKERS = {
    "fix this",
    "write this",
    "generate this",
    "do this task",
    "帮我",
    "请帮我",
    "修复",
    "写一个",
}

STABILITY_MARKERS = {
    "usually",
    "often",
    "always",
    "tend to",
    "keep",
    "still",
    "again",
    "long-term",
    "长期",
    "一直",
    "经常",
    "通常",
    "持续",
}

COMMUNICATION_HINTS = {
    "answer",
    "answers",
    "response",
    "responses",
    "tone",
    "communication",
    "writeup",
    "summary",
    "summaries",
    "json",
    "structured",
    "concise",
    "verbose",
    "detail",
    "direct",
    "markdown",
    "output",
    "输出",
    "回答",
    "语气",
    "结构化",
    "简洁",
}

WORKFLOW_HINTS = {
    "cli",
    "command line",
    "local",
    "local-first",
    "offline",
    "python",
    "tooling",
    "automation",
    "json",
    "markdown",
    "file",
    "storage",
    "gui",
    "terminal",
}

EMOTIONAL_HINTS = {
    "warm",
    "friendly",
    "calm",
    "direct",
    "blunt",
    "patronizing",
    "fluffy",
    "marketing",
    "hype",
    "judgmental",
    "tone",
}

EXTRACTION_PATTERNS: list[ExtractionPattern] = [
    ExtractionPattern(
        name="style_en",
        regex=re.compile(
            r"\b(?:please keep|please make|keep|make)\s+(?:the\s+)?(?:answers?|responses?|output|tone)\s+(?P<value>[^.!?\n;]+)",
            re.IGNORECASE,
        ),
        candidate_type="style",
        base_confidence=0.74,
        canonical_prefix="prefers",
    ),
    ExtractionPattern(
        name="style_en_be",
        regex=re.compile(
            r"\b(?:answers?|responses?|output|tone)\s+(?:should|must)\s+be\s+(?P<value>[^.!?\n;]+)",
            re.IGNORECASE,
        ),
        candidate_type="style",
        base_confidence=0.72,
        canonical_prefix="prefers",
    ),
    ExtractionPattern(
        name="style_zh",
        regex=re.compile(r"(?:请保持|请让)(?:回答|输出|语气)?(?P<value>[^。！？\n；]+)"),
        candidate_type="style",
        base_confidence=0.74,
        canonical_prefix="prefers",
    ),
    ExtractionPattern(
        name="preference_en",
        regex=re.compile(
            r"\b(?:i prefer|i really prefer|i like|i love|i enjoy)\s+(?P<value>[^.!?\n;]+)",
            re.IGNORECASE,
        ),
        candidate_type="preference",
        base_confidence=0.68,
        canonical_prefix="prefers",
    ),
    ExtractionPattern(
        name="preference_zh",
        regex=re.compile(r"(?:我偏好|我更喜欢|我喜欢|我享受)\s*(?P<value>[^。！？\n；]+)"),
        candidate_type="preference",
        base_confidence=0.68,
        canonical_prefix="prefers",
    ),
    ExtractionPattern(
        name="negative_en",
        regex=re.compile(
            r"\b(?:i dislike|i hate|i don't like|please avoid|avoid)\s+(?P<value>[^.!?\n;]+)",
            re.IGNORECASE,
        ),
        candidate_type="taboo",
        base_confidence=0.72,
        canonical_prefix="avoids",
    ),
    ExtractionPattern(
        name="negative_zh",
        regex=re.compile(r"(?:我不喜欢|我讨厌|请避免|避免|不要)\s*(?P<value>[^。！？\n；]+)"),
        candidate_type="taboo",
        base_confidence=0.72,
        canonical_prefix="avoids",
    ),
    ExtractionPattern(
        name="project_en",
        regex=re.compile(
            r"\b(?:i am building|i'm building|i am working on|i'm working on|i am still working on|i'm still working on|my project is|we are building|we're building)\s+(?P<value>[^.!?\n;]+)",
            re.IGNORECASE,
        ),
        candidate_type="project",
        base_confidence=0.76,
        canonical_prefix="works on",
    ),
    ExtractionPattern(
        name="project_zh",
        regex=re.compile(r"(?:我在做|我正在做|我还在做|我在构建|我正在构建|我的项目是)\s*(?P<value>[^。！？\n；]+)"),
        candidate_type="project",
        base_confidence=0.76,
        canonical_prefix="works on",
    ),
    ExtractionPattern(
        name="goal_en",
        regex=re.compile(
            r"\b(?:i want to|i need to|my goal is to|i am trying to|i'm trying to)\s+(?P<value>[^.!?\n;]+)",
            re.IGNORECASE,
        ),
        candidate_type="goal",
        base_confidence=0.7,
        canonical_prefix="aims to",
    ),
    ExtractionPattern(
        name="goal_zh",
        regex=re.compile(r"(?:我想要|我需要|我的目标是|我在尝试)\s*(?P<value>[^。！？\n；]+)"),
        candidate_type="goal",
        base_confidence=0.7,
        canonical_prefix="aims to",
    ),
    ExtractionPattern(
        name="worldview_en",
        regex=re.compile(
            r"\b(?:i value|i care about|it's important to me that)\s+(?P<value>[^.!?\n;]+)",
            re.IGNORECASE,
        ),
        candidate_type="worldview",
        base_confidence=0.74,
        canonical_prefix="values",
    ),
    ExtractionPattern(
        name="worldview_zh",
        regex=re.compile(r"(?:我重视|我在乎|对我来说很重要的是)\s*(?P<value>[^。！？\n；]+)"),
        candidate_type="worldview",
        base_confidence=0.74,
        canonical_prefix="values",
    ),
    ExtractionPattern(
        name="routine_en",
        regex=re.compile(
            r"\b(?:i usually|i often|i tend to|i always)\s+(?P<value>[^.!?\n;]+)",
            re.IGNORECASE,
        ),
        candidate_type="routine",
        base_confidence=0.66,
        canonical_prefix="often",
    ),
    ExtractionPattern(
        name="routine_zh",
        regex=re.compile(r"(?:我通常|我经常|我总是|我倾向于)\s*(?P<value>[^。！？\n；]+)"),
        candidate_type="routine",
        base_confidence=0.66,
        canonical_prefix="often",
    ),
    ExtractionPattern(
        name="constraint_en",
        regex=re.compile(
            r"\b(?:i only use|i mainly use|i primarily use|i mostly use|i use)\s+(?P<value>[^.!?\n;]+)",
            re.IGNORECASE,
        ),
        candidate_type="constraint",
        base_confidence=0.62,
        canonical_prefix="uses",
    ),
    ExtractionPattern(
        name="constraint_zh",
        regex=re.compile(r"(?:我只用|我主要用|我基本都用|我用)\s*(?P<value>[^。！？\n；]+)"),
        candidate_type="constraint",
        base_confidence=0.62,
        canonical_prefix="uses",
    ),
    ExtractionPattern(
        name="identity_en",
        regex=re.compile(
            r"\b(?:i am|i'm)\s+(?:a|an)?\s*(?P<value>(?:writer|developer|designer|researcher|teacher|student|artist|engineer)[^.!?\n;]*)",
            re.IGNORECASE,
        ),
        candidate_type="identity",
        base_confidence=0.7,
        canonical_prefix="identifies as",
    ),
    ExtractionPattern(
        name="identity_zh",
        regex=re.compile(r"(?:我是)\s*(?P<value>(?:作者|开发者|设计师|研究者|老师|学生|艺术家|工程师)[^。！？\n；]*)"),
        candidate_type="identity",
        base_confidence=0.7,
        canonical_prefix="identifies as",
    ),
]
