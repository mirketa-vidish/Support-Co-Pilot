"""Local, offline embedding model - no API key or network call needed at query time.

The model weights are pulled from HuggingFace once (cached under ~/.cache) the
first time this runs, then everything works fully offline.

huggingface_hub otherwise still sends a HEAD request per file on every model
load / encode call to revalidate the cache against the hub, even when nothing
changed - if huggingface.co is slow or unreachable (proxy, VPN, flaky network),
those checks stall for a long time before eventually failing. Since the model
is already cached after the first run, force offline mode so it's never
attempted.
"""

import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from sentence_transformers import SentenceTransformer  # noqa: E402

from .config import settings  # noqa: E402

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(settings.embedding_model)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return get_model().encode(texts, normalize_embeddings=True).tolist()


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
