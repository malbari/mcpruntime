"""Context provider abstraction for MCPRuntime.

This module defines the abstract base classes for context providers that
supply structured knowledge to agents before execution and learn from
execution outcomes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator, Any, List


@dataclass
class ContextResult:
    """Structured context result returned to the executor.

    Attributes:
        context: The structured context dictionary for the agent
        confidence: 0-1 score indicating how well context covers this task
        coverage: 0-1 score indicating how observed this task pattern is
        novel: True if agent has not seen this task shape before
        suggested_skills: Pre-filtered skills from registry before execution
    """
    context: dict
    confidence: float = 0.0
    coverage: float = 0.0
    novel: bool = True
    suggested_skills: List[str] = field(default_factory=list)


@dataclass
class ExecutionOutcome:
    """Outcome of an execution for learning.

    Attributes:
        success: Whether execution completed without error
        objective_met: Whether the stated goal was achieved
        confidence_delta: Measured change in confidence post-execution
        task: The original task description
        objective: The objective that was attempted
    """
    success: bool
    objective_met: bool
    confidence_delta: float
    task: str
    objective: str


class ContextProvider(ABC):
    """Provides structured context to the agent before execution.

    Override this class to supply any domain-specific knowledge source.
    The context provider is responsible for:
    1. Retrieving relevant context for a given task
    2. Updating its knowledge based on execution outcomes (learning loop)

    Example:
        ```python
        class MyKnowledgeBase(ContextProvider):
            def get_context(self, task: str) -> ContextResult:
                # Query your knowledge base
                return ContextResult(context={"relevant": "data"})

            def update(self, task: str, outcome: ExecutionOutcome) -> None:
                # Update your knowledge base
                pass
        ```
    """

    @abstractmethod
    def get_context(self, task: str) -> ContextResult:
        """Retrieve context for a given task.

        Args:
            task: The task description or query

        Returns:
            ContextResult containing structured context and metadata
        """
        ...

    @abstractmethod
    def update(self, task: str, outcome: ExecutionOutcome) -> None:
        """Called after every execution to close the learning loop.

        Implement this method to update your knowledge source based on
        execution outcomes. This enables the system to improve over time.

        Args:
            task: The task that was executed
            outcome: The outcome of the execution
        """
        ...


class QueryableContextProvider(ContextProvider):
    """Extended context provider supporting structured traversal.

    Required for RLM-based execution. A flat ContextProvider is insufficient
    when context is too large to retrieve in a single call.

    Implement this if your context source supports:
    - Structured queries over large datasets
    - Traversal operations (depth-limited search)
    - Iterative refinement of context

    Example:
        ```python
        class GraphKnowledgeBase(QueryableContextProvider):
            def query(self, expression: str, depth: int = 1) -> Iterator[dict]:
                # Traverse knowledge graph
                for node in self.graph.query(expression, depth):
                    yield node.to_dict()
        ```
    """

    @abstractmethod
    def query(self, expression: str, depth: int = 1) -> Iterator[dict]:
        """Execute a structured query over the context.

        Args:
            expression: Query expression (syntax depends on implementation)
            depth: How many levels of traversal to perform

        Returns:
            Iterator yielding context chunks as dictionaries

        Raises:
            TypeError: If passed to RecursiveAgent without implementation
        """
        ...
