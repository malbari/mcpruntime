"""Compatibility shim: streaming moved to mcpruntime.core.streaming."""

from mcpruntime.core.streaming import StreamingExecutor

__all__ = ["StreamingExecutor"]
