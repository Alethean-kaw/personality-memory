from __future__ import annotations

from difflib import SequenceMatcher

from .utils import clamp, normalize_text, tokenize

STOPWORDS = {
    "a",
    "an",
    "and",
    "the",
    "to",
    "for",
    "of",
    "that",
    "is",
    "be",
    "with",
    "on",
    "my",
    "i",
    "it",
    "me",
    "we",
    "our",
    "this",
    "these",
    "those",
    "please",
    "answer",
    "answers",
    "response",
    "responses",
}

ANTONYM_PAIRS = [
    ({"prefer", "prefers", "like", "likes", "value", "values"}, {"avoid", "avoids", "dislike", "dislikes", "hate", "hates"}),
    ({"concise", "brief", "short"}, {"verbose", "long", "detailed"}),
    ({"local", "local-first", "offline"}, {"cloud", "hosted"}),
    ({"cli", "terminal"}, {"gui", "graphical"}),
    ({"json", "structured"}, {"freeform", "unstructured"}),
    ({"warm", "friendly"}, {"cold", "harsh"}),
]


def normalized_token_set(text: str) -> set[str]:
    return {
        token
        for token in tokenize(text)
        if token not in STOPWORDS and len(token) > 1
    }


def similarity_score(left: str, right: str) -> float:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0

    left_tokens = normalized_token_set(left_norm)
    right_tokens = normalized_token_set(right_norm)
    if not left_tokens or not right_tokens:
        return SequenceMatcher(None, left_norm, right_norm).ratio()

    jaccard = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    containment = 1.0 if left_norm in right_norm or right_norm in left_norm else 0.0
    return clamp((0.5 * jaccard) + (0.35 * sequence) + (0.15 * containment))


def contradiction_score(left: str, right: str) -> float:
    left_tokens = normalized_token_set(left)
    right_tokens = normalized_token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0

    overlap = len(left_tokens & right_tokens)
    if overlap == 0:
        return 0.0

    score = 0.0
    for positives, negatives in ANTONYM_PAIRS:
        if (left_tokens & positives and right_tokens & negatives) or (left_tokens & negatives and right_tokens & positives):
            score += 0.35

    if ("avoids" in left_tokens and "prefers" in right_tokens) or ("prefers" in left_tokens and "avoids" in right_tokens):
        score += 0.2

    if overlap >= 2:
        score += 0.15

    return clamp(score)


def candidate_confidence(
    *,
    base_confidence: float,
    has_stability_marker: bool,
    has_temporal_noise: bool,
    fragment_length: int,
    source_text: str,
) -> float:
    score = base_confidence
    if has_stability_marker:
        score += 0.08
    if has_temporal_noise:
        score -= 0.18
    if 3 <= fragment_length <= 14:
        score += 0.05
    elif fragment_length > 22:
        score -= 0.05
    if "because" in source_text or "so that" in source_text:
        score += 0.02
    return clamp(score, 0.0, 0.99)


def signal_strength(confidence: float) -> str:
    if confidence >= 0.82:
        return "strong"
    if confidence >= 0.67:
        return "medium"
    return "weak"
