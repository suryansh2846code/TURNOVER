"""Pluggable embedding providers.

The whole app is designed to run with zero external dependencies or network
access via the deterministic `hash` provider, then upgrade transparently to a
real semantic model (local sentence-transformers, OpenAI, or Gemini) by
flipping one env var. All providers return L2-normalized float32 vectors, so
recall (cosine == dot product) works identically regardless of provider.
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache

import numpy as np

from ..config import get_settings

_TOKEN = re.compile(r"[a-z0-9]+")


class Embedder:
    dim: int = 256
    name: str = "base"

    def embed(self, texts: list[str]) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a search query. Retrieval models (BGE/E5) want an instruction
        prefix on queries only; the default treats query == passage."""
        return self.embed_one(text)


def _normalize(v: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(v, axis=-1, keepdims=True)
    norm[norm == 0] = 1.0
    return (v / norm).astype(np.float32)


class HashEmbedder(Embedder):
    """Offline, dependency-free hashing embedding.

    A bag-of-words feature-hashing vectorizer with sub-word shingles. It has no
    world knowledge, but it captures lexical overlap well enough for useful
    recall and guarantees the app works on first run with nothing installed.
    """

    name = "hash"

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def _features(self, text: str) -> list[str]:
        words = _TOKEN.findall(text.lower())
        feats: list[str] = list(words)
        # character trigrams give partial-match robustness
        for w in words:
            padded = f"#{w}#"
            feats += [padded[i : i + 3] for i in range(len(padded) - 2)]
        return feats

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for feat in self._features(text):
                h = int.from_bytes(
                    hashlib.blake2b(feat.encode(), digest_size=8).digest(), "little"
                )
                idx = h % self.dim
                sign = 1.0 if (h >> 63) & 1 else -1.0
                out[row, idx] += sign
        return _normalize(out)


class SentenceTransformerEmbedder(Embedder):
    name = "local"

    def __init__(self, model: str | None = None) -> None:
        import logging
        import os

        # quiet the noisy HF/transformers startup logging
        for name in ("transformers", "sentence_transformers", "httpx",
                     "huggingface_hub"):
            logging.getLogger(name).setLevel(logging.ERROR)

        from sentence_transformers import SentenceTransformer  # lazy

        self.model_name = model or "all-MiniLM-L6-v2"
        # Local-first: after the first download the model is cached, so load
        # OFFLINE (no network, fast, no HF update checks). Fall back to an online
        # load only if it isn't cached yet.
        try:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            self._model = SentenceTransformer(self.model_name)
        except Exception:
            os.environ.pop("HF_HUB_OFFLINE", None)
            os.environ.pop("TRANSFORMERS_OFFLINE", None)
            self._model = SentenceTransformer(self.model_name)  # downloads + caches
        try:
            self.dim = self._model.get_embedding_dimension()
        except AttributeError:  # older sentence-transformers
            self.dim = self._model.get_sentence_embedding_dimension()
        # retrieval models rank far better with an instruction on the QUERY only
        low = self.model_name.lower()
        if "bge" in low:
            self._query_prefix = "Represent this sentence for searching relevant passages: "
        elif "e5" in low:
            self._query_prefix = "query: "
        else:
            self._query_prefix = ""

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = self._model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vecs, dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_one(self._query_prefix + text)


class OpenAIEmbedder(Embedder):
    name = "openai"

    def __init__(self, model: str | None = None) -> None:
        self.model_name = model or "text-embedding-3-small"
        self.dim = 1536 if "small" in self.model_name else 3072
        s = get_settings()
        if not s.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for the openai embedder")
        self._key = s.openai_api_key

    def embed(self, texts: list[str]) -> np.ndarray:
        import httpx

        resp = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self._key}"},
            json={"model": self.model_name, "input": texts},
            timeout=60,
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        return _normalize(np.asarray([d["embedding"] for d in data], dtype=np.float32))


class GeminiEmbedder(Embedder):
    name = "gemini"

    def __init__(self, model: str | None = None) -> None:
        self.model_name = model or "text-embedding-004"
        self.dim = 768
        s = get_settings()
        if not s.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is required for the gemini embedder")
        self._key = s.gemini_api_key

    def embed(self, texts: list[str]) -> np.ndarray:
        import httpx

        out = []
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self.model_name}:embedContent?key={self._key}"
        )
        for text in texts:
            resp = httpx.post(
                url,
                json={"content": {"parts": [{"text": text}]}},
                timeout=60,
            )
            resp.raise_for_status()
            out.append(resp.json()["embedding"]["values"])
        return _normalize(np.asarray(out, dtype=np.float32))


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    provider = (s.embedding_provider or "hash").lower()
    try:
        if provider == "local":
            return SentenceTransformerEmbedder(s.embedding_model)
        if provider == "openai":
            return OpenAIEmbedder(s.embedding_model)
        if provider == "gemini":
            return GeminiEmbedder(s.embedding_model)
    except Exception as exc:  # graceful downgrade keeps the app usable
        import sys

        print(
            f"[lodestone] embedding provider '{provider}' unavailable ({exc}); "
            "falling back to offline 'hash' embedder.",
            file=sys.stderr,
        )
    return HashEmbedder()
