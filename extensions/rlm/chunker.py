"""Context slicing for recursive queries.

This module provides utilities for chunking large context into
manageable pieces for recursive processing.
"""

import logging
from typing import Iterator, List, Optional, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """A chunk of context data.

    Attributes:
        content: The chunk content
        index: Chunk index in sequence
        total: Total number of chunks
        metadata: Optional metadata about the chunk
    """
    content: str
    index: int
    total: int
    metadata: Optional[dict] = None


class ContextChunker:
    """Chunks large context into processable pieces.

    The chunker provides multiple strategies for dividing context:
    - Fixed size: Equal-sized chunks
    - Delimiter: Split on specific characters (e.g., newlines)
    - Semantic: Split on semantic boundaries (paragraphs, sentences)

    Example:
        ```python
        chunker = ContextChunker(max_chunk_size=2000)
        chunks = chunker.chunk(text)
        for chunk in chunks:
            result = process(chunk.content)
        ```
    """

    def __init__(
        self,
        max_chunk_size: int = 2000,
        overlap: int = 200,
        strategy: str = "fixed"
    ):
        """Initialize the chunker.

        Args:
            max_chunk_size: Maximum characters per chunk
            overlap: Number of characters to overlap between chunks
            strategy: Chunking strategy ("fixed", "line", "paragraph")
        """
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap
        self.strategy = strategy

    def chunk(self, text: str) -> Iterator[Chunk]:
        """Chunk text according to the configured strategy.

        Args:
            text: Text to chunk

        Yields:
            Chunk objects
        """
        if self.strategy == "fixed":
            yield from self._chunk_fixed(text)
        elif self.strategy == "line":
            yield from self._chunk_line(text)
        elif self.strategy == "paragraph":
            yield from self._chunk_paragraph(text)
        else:
            raise ValueError(f"Unknown strategy: {self.strategy}")

    def _chunk_fixed(self, text: str) -> Iterator[Chunk]:
        """Chunk by fixed size with overlap."""
        total = max(1, (len(text) + self.max_chunk_size - 1) // self.max_chunk_size)
        start = 0
        index = 0

        while start < len(text):
            end = min(start + self.max_chunk_size, len(text))
            content = text[start:end]

            yield Chunk(
                content=content,
                index=index,
                total=total,
                metadata={"start": start, "end": end}
            )

            # Move start, accounting for overlap
            start = end - self.overlap if end < len(text) else end
            index += 1

    def _chunk_line(self, text: str) -> Iterator[Chunk]:
        """Chunk by lines, respecting max size."""
        lines = text.split('\n')
        chunks = []
        current = []
        current_len = 0

        for line in lines:
            line_len = len(line) + 1  # +1 for newline

            if current_len + line_len > self.max_chunk_size and current:
                chunks.append('\n'.join(current))
                current = []
                current_len = 0

            current.append(line)
            current_len += line_len

        if current:
            chunks.append('\n'.join(current))

        total = len(chunks)
        for i, content in enumerate(chunks):
            yield Chunk(content=content, index=i, total=total)

    def _chunk_paragraph(self, text: str) -> Iterator[Chunk]:
        """Chunk by paragraphs, respecting max size."""
        paragraphs = text.split('\n\n')
        chunks = []
        current = []
        current_len = 0

        for para in paragraphs:
            para_len = len(para) + 2  # +2 for paragraph breaks

            if current_len + para_len > self.max_chunk_size and current:
                chunks.append('\n\n'.join(current))
                current = []
                current_len = 0

            current.append(para)
            current_len += para_len

        if current:
            chunks.append('\n\n'.join(current))

        total = len(chunks)
        for i, content in enumerate(chunks):
            yield Chunk(content=content, index=i, total=total)


class SmartChunker(ContextChunker):
    """Chunker with content-aware splitting.

    Attempts to split at natural boundaries (sentences, list items)
    while respecting size constraints.
    """

    def __init__(
        self,
        max_chunk_size: int = 2000,
        overlap: int = 200,
        respect_boundaries: bool = True
    ):
        """Initialize smart chunker.

        Args:
            max_chunk_size: Maximum chunk size
            overlap: Overlap between chunks
            respect_boundaries: Try to split at sentence boundaries
        """
        super().__init__(max_chunk_size, overlap, "fixed")
        self.respect_boundaries = respect_boundaries

    def chunk(self, text: str) -> Iterator[Chunk]:
        """Chunk with boundary awareness."""
        if not self.respect_boundaries:
            yield from super().chunk(text)
            return

        # Try to split at sentence boundaries
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text)

        chunks = []
        current = []
        current_len = 0

        for sent in sentences:
            sent_len = len(sent) + 1

            if current_len + sent_len > self.max_chunk_size and current:
                chunks.append(' '.join(current))
                # Keep last sentence for overlap if possible
                if len(current) > 1:
                    current = [current[-1]]
                    current_len = len(current[0]) + 1
                else:
                    current = []
                    current_len = 0

            current.append(sent)
            current_len += sent_len

        if current:
            chunks.append(' '.join(current))

        total = len(chunks)
        for i, content in enumerate(chunks):
            yield Chunk(content=content, index=i, total=total)


def chunk_with_callback(
    text: str,
    callback: Callable[[Chunk], Optional[str]],
    max_chunk_size: int = 2000,
    stop_on_result: bool = True
) -> List[str]:
    """Chunk text and apply callback to each chunk.

    Args:
        text: Text to chunk
        callback: Function to apply to each chunk
        max_chunk_size: Maximum chunk size
        stop_on_result: Stop when callback returns non-None

    Returns:
        List of callback results
    """
    chunker = ContextChunker(max_chunk_size=max_chunk_size)
    results = []

    for chunk in chunker.chunk(text):
        result = callback(chunk)
        if result is not None:
            results.append(result)
            if stop_on_result:
                break

    return results
