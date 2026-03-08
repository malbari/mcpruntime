"""Context layer for MCPRuntime.

This module contains the pluggable context system:
- provider: Abstract base classes for context providers
- default: File-based and in-memory implementations
- context_tools: MCP tools for context operations

Extend the context layer by implementing ContextProvider or
QueryableContextProvider for your knowledge source.
"""

from mcpruntime.context.provider import (
    ContextProvider,
    QueryableContextProvider,
    ContextResult,
    ExecutionOutcome,
)
from mcpruntime.context.default import (
    FileContextProvider,
    InMemoryContextProvider,
)

__all__ = [
    "ContextProvider",
    "QueryableContextProvider",
    "ContextResult",
    "ExecutionOutcome",
    "FileContextProvider",
    "InMemoryContextProvider",
]
