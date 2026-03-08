"""Recursive Language Models (RLM) extension.

Advanced capability for processing infinite context through
recursive querying. Requires QueryableContextProvider.

This extension only activates when you have a context source
large enough to require structured traversal.
"""

from extensions.rlm.agent import RecursiveAgent
from extensions.rlm.chunker import ContextChunker, SmartChunker, Chunk

__all__ = [
    "RecursiveAgent",
    "ContextChunker",
    "SmartChunker",
    "Chunk",
]
