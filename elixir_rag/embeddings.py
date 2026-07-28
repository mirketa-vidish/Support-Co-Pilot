"""Local, offline embedding model - no API key or network call needed at query time.

The model weights are pulled from HuggingFace once (cached under ~/.cache) the
first time this runs, then everything works fully offline.

huggingface_hub otherwise still sends a HEAD request per file on every model
load / encode call to revalidate the cache against the hub, even when nothing
changed - if huggingface.co is slow or unreachable (proxy, VPN, flaky network),
those checks stall for a long time before eventually failing. Once the model
is already cached, force offline mode so that's never attempted.

That check has to happen *before* the model is cached at all, though - on a
brand-new machine that's never downloaded it, forcing offline mode from the
very first run makes the initial download impossible and fails with a
confusing "couldn't connect and couldn't find it in the cache" error. So: go
offline only once a real, complete cached copy is confirmed on disk; the very
first run for anyone stays online just long enough to download it once.
"""

import os
from pathlib import Path


def _is_cached_locally(model_name: str) -> bool:
    cache_dir = os.environ.get("HUGGINGFACE_HUB_CACHE") or os.path.join(
        os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface")), "hub"
    )
    snapshots_dir = Path(cache_dir) / f"models--{model_name.replace('/', '--')}" / "snapshots"
    return snapshots_dir.is_dir() and any(snapshots_dir.iterdir())


from .config import settings  # noqa: E402

if _is_cached_locally(settings.embedding_model):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from sentence_transformers import SentenceTransformer  # noqa: E402

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
