from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .scoring import hybrid_similarity_score, lexical_similarity_score


@runtime_checkable
class SimilarityBackend(Protocol):
    name: str

    def similarity(self, left: str, right: str) -> float: ...


@dataclass(slots=True, frozen=True)
class LexicalSimilarityBackend:
    name: str = "lexical"

    def similarity(self, left: str, right: str) -> float:
        return lexical_similarity_score(left, right)


@dataclass(slots=True, frozen=True)
class HybridSimilarityBackend:
    name: str = "hybrid"

    def similarity(self, left: str, right: str) -> float:
        return hybrid_similarity_score(left, right)


_BACKENDS: dict[str, SimilarityBackend] = {
    "lexical": LexicalSimilarityBackend(),
    "hybrid": HybridSimilarityBackend(),
}


def register_backend(backend: SimilarityBackend) -> None:
    _BACKENDS[backend.name] = backend


def get_backend(name: str = "hybrid") -> SimilarityBackend:
    try:
        return _BACKENDS[name]
    except KeyError as exc:
        known = ", ".join(sorted(_BACKENDS))
        raise ValueError(f"Unknown similarity backend '{name}'. Known backends: {known}.") from exc


def list_backends() -> list[str]:
    return sorted(_BACKENDS)
