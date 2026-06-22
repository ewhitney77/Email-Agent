"""Semantic matching.

Embeds posting text and every "ideal role" sample, then scores a posting by the
maximum cosine similarity against any sample. Two embedding backends are
supported:

  * "sentence-transformers"  -> free, fully local (default)
  * "openai"                 -> text-embedding-3-small / ada-002 (needs API key)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import Config


# --------------------------------------------------------------------------- #
# Embedding backends
# --------------------------------------------------------------------------- #
class _Embedder:
    def embed(self, texts: list[str]) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError


class _SentenceTransformerEmbedder(_Embedder):
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(
            self.model.encode(texts, normalize_embeddings=False, show_progress_bar=False),
            dtype=np.float32,
        )


class _OpenAIEmbedder(_Embedder):
    def __init__(self, model_name: str, api_key: str):
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for the openai backend")
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model_name = model_name

    def embed(self, texts: list[str]) -> np.ndarray:
        # OpenAI rejects empty strings; substitute a single space.
        cleaned = [t if t.strip() else " " for t in texts]
        resp = self.client.embeddings.create(model=self.model_name, input=cleaned)
        return np.asarray([d.embedding for d in resp.data], dtype=np.float32)


def build_embedder(cfg: Config) -> _Embedder:
    backend = cfg.embedding_backend.lower()
    if backend in {"openai", "ada", "text-embedding-ada-002"}:
        return _OpenAIEmbedder(cfg.openai_model, cfg.openai_api_key)
    return _SentenceTransformerEmbedder(cfg.st_model)


# --------------------------------------------------------------------------- #
# Similarity
# --------------------------------------------------------------------------- #
def _cosine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a_norm = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-10)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-10)
    return a_norm @ b_norm.T


@dataclass
class MatchResult:
    score: float
    best_role: str


class SemanticMatcher:
    """Holds the embedded ideal-role corpus and scores new postings against it."""

    def __init__(self, cfg: Config, ideal_dir: Path):
        self.cfg = cfg
        self.embedder = build_embedder(cfg)
        self.role_names: list[str] = []
        self.role_vectors: np.ndarray | None = None
        self._load_ideal_roles(ideal_dir)

    def _load_ideal_roles(self, ideal_dir: Path) -> None:
        files = sorted(ideal_dir.glob("*.txt")) if ideal_dir.exists() else []
        if not files:
            raise FileNotFoundError(
                f"No .txt ideal-role files found in {ideal_dir}. "
                "Add at least one sample job description to calibrate matching."
            )
        texts = []
        for f in files:
            self.role_names.append(f.stem)
            texts.append(f.read_text(encoding="utf-8"))
        self.role_vectors = self.embedder.embed(texts)

    def score(self, text: str) -> MatchResult:
        if not text.strip() or self.role_vectors is None:
            return MatchResult(score=0.0, best_role="")
        vec = self.embedder.embed([text])
        sims = _cosine(vec, self.role_vectors)[0]
        best_idx = int(np.argmax(sims))
        return MatchResult(score=float(sims[best_idx]), best_role=self.role_names[best_idx])

    def is_match(self, text: str) -> tuple[bool, MatchResult]:
        result = self.score(text)
        return result.score >= self.cfg.threshold, result
