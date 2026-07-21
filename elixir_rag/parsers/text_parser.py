"""Parses plain-text/markdown inputs (issue replication steps) into chunks."""

from ..chunking import chunk_text


def parse_text(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    return chunk_text(content)
