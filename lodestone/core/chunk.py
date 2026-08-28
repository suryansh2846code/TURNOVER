"""Text chunking for ingestion.

Splits long documents into overlapping, paragraph-aware chunks so each stored
memory is a self-contained, embeddable unit.
"""
from __future__ import annotations

import re

_PARA = re.compile(r"\n\s*\n")


def chunk_text(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # Prefer paragraph boundaries; fall back to hard slicing for giant blocks.
    paras = [p.strip() for p in _PARA.split(text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paras:
        if len(para) > max_chars:
            if buf:
                chunks.append(buf)
                buf = ""
            for i in range(0, len(para), max_chars - overlap):
                chunks.append(para[i : i + max_chars])
            continue
        if len(buf) + len(para) + 2 <= max_chars:
            buf = f"{buf}\n\n{para}" if buf else para
        else:
            chunks.append(buf)
            buf = para
    if buf:
        chunks.append(buf)
    return chunks
