"""Parses an SFDX project directory into per-file chunks.

Each source file is chunked on its own (never merged with another file's
content), and every chunk is prefixed with its file path - the single most
useful piece of context when the LLM is later trying to reason about
"which class/trigger does this belong to."
"""

import os

from ..chunking import chunk_text

CODE_EXTENSIONS = {
    ".cls", ".trigger", ".cmp", ".js", ".xml", ".page", ".flow-meta.xml",
    ".object-meta.xml", ".field-meta.xml", ".layout-meta.xml", ".html", ".css",
}

SKIP_DIR_NAMES = {".sfdx", ".sf", "node_modules", ".git", "__pycache__"}


def _iter_source_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        for filename in filenames:
            if any(filename.endswith(ext) for ext in CODE_EXTENSIONS):
                yield os.path.join(dirpath, filename)


def parse_sfdx_project(root: str) -> list[tuple[str, list[str]]]:
    """Returns a list of (relative_source_file, chunks) pairs for every source file found."""
    results = []
    for filepath in _iter_source_files(root):
        rel_path = os.path.relpath(filepath, root).replace("\\", "/")
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            continue
        if not content.strip():
            continue
        annotated = f"File: {rel_path}\n\n{content}"
        chunks = chunk_text(annotated)
        results.append((rel_path, chunks))
    return results
