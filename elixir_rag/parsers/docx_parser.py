"""Parses a Solution Design Document (Word .docx) into chunks.

Headings are carried forward and prefixed onto the body text under them, so
a chunk about (say) "Known Limitations" still says "Known Limitations" even
if the heading itself ended up in the previous chunk - this keeps section
context intact for retrieval.
"""

import docx

from ..chunking import chunk_text


def parse_docx(path: str) -> list[str]:
    document = docx.Document(path)

    sections: list[tuple[str, list[str]]] = []
    current_heading = "Document Start"
    current_body: list[str] = []

    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        if para.style.name.startswith("Heading") or para.style.name == "Title":
            if current_body:
                sections.append((current_heading, current_body))
            current_heading = text
            current_body = []
        else:
            current_body.append(text)
    if current_body:
        sections.append((current_heading, current_body))

    for table in document.tables:
        rows_text = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            rows_text.append(" | ".join(cells))
        if rows_text:
            sections.append(("Table", rows_text))

    chunks = []
    for heading, body_lines in sections:
        section_text = f"## {heading}\n" + "\n".join(body_lines)
        chunks.extend(chunk_text(section_text))
    return chunks
