"""Generic text chunking shared by all document parsers.

Chunks are measured in characters, not tokens - close enough for a local
MiniLM embedding model (max ~256 tokens) without pulling in a tokenizer
just for this.
"""

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping windows, breaking on paragraph/line boundaries where possible."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [line for line in text.split("\n") if line.strip()]

    chunks = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)
        if len(para) <= chunk_size:
            current = para
        else:
            # A single paragraph is itself too big (e.g. dense log block) - hard-split it.
            for i in range(0, len(para), chunk_size - overlap):
                chunks.append(para[i:i + chunk_size])
            current = ""

    if current:
        chunks.append(current)

    # Stitch overlap between adjacent chunks so retrieval doesn't lose context at boundaries.
    overlapped = []
    for i, chunk in enumerate(chunks):
        if i == 0:
            overlapped.append(chunk)
        else:
            prev_tail = chunks[i - 1][-overlap:]
            overlapped.append(f"{prev_tail}\n{chunk}")
    return overlapped
