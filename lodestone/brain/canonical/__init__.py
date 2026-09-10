"""Canonical Brain — a curated, source-backed, versioned model of the user,
layered ABOVE the raw source index and knowledge graph (which stay unchanged).

Public entry point:
    from lodestone.brain.canonical import get_canonical
    cb = get_canonical()
    cb.learn_from_conversation(user_text)      # grow it over time
    cb.recall_block(query)["block"]            # canonical-first context
"""
from .service import CanonicalBrain, get_canonical

__all__ = ["CanonicalBrain", "get_canonical"]
