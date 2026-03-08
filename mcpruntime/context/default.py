"""Default file-based context provider implementation.

This module provides a minimal concrete implementation of ContextProvider
that reads context from a local directory of markdown or JSON files.

This implementation is deliberately simple — its limitations should be
obvious, pointing developers toward richer implementations when needed.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from mcpruntime.context.provider import ContextProvider, ContextResult, ExecutionOutcome


class FileContextProvider(ContextProvider):
    """A file-based context provider for local development.

    Reads context from a directory of markdown or JSON files.
    Writes outcomes to a JSONL log for later analysis.

    Confidence and coverage are computed heuristically from:
    - How many prior successful executions exist for similar tasks
    - Keyword overlap between task and available context files

    Attributes:
        context_dir: Directory containing context files (.md, .json)
        outcomes_log: Path to JSONL file for execution outcomes

    Example:
        ```python
        provider = FileContextProvider("./context")
        result = provider.get_context("Process customer orders")
        # result.confidence based on prior similar task success
        ```
    """

    def __init__(
        self,
        context_dir: str = "./context",
        outcomes_log: str = "./context/outcomes.jsonl"
    ):
        """Initialize the file-based context provider.

        Args:
            context_dir: Directory containing context files
            outcomes_log: Path to write execution outcomes
        """
        self.context_dir = Path(context_dir)
        self.outcomes_log = Path(outcomes_log)
        self._outcomes: List[Dict[str, Any]] = []
        self._load_outcomes()

    def _load_outcomes(self) -> None:
        """Load historical outcomes from JSONL file."""
        if not self.outcomes_log.exists():
            return

        try:
            with open(self.outcomes_log, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self._outcomes.append(json.loads(line))
        except (json.JSONDecodeError, IOError):
            # If file is corrupted, start fresh
            self._outcomes = []

    def _find_context_files(self) -> List[Path]:
        """Find all context files in the context directory."""
        if not self.context_dir.exists():
            return []

        files = []
        for ext in [".md", ".json"]:
            files.extend(self.context_dir.glob(f"**/*{ext}"))
        return files

    def _read_context_file(self, path: Path) -> Dict[str, Any]:
        """Read a context file and return its contents."""
        try:
            content = path.read_text(encoding="utf-8")

            if path.suffix == ".json":
                return json.loads(content)
            else:
                # Treat markdown as structured text
                return {
                    "type": "text",
                    "source": str(path),
                    "content": content,
                    "title": self._extract_title(content, path)
                }
        except (IOError, json.JSONDecodeError) as e:
            return {
                "type": "error",
                "source": str(path),
                "error": str(e)
            }

    def _extract_title(self, content: str, path: Path) -> str:
        """Extract title from markdown content or filename."""
        # Try to find first heading
        match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return path.stem.replace('_', ' ').replace('-', ' ').title()

    def _compute_similarity(self, task: str, context: Dict[str, Any]) -> float:
        """Compute simple keyword overlap similarity."""
        task_words = set(task.lower().split())

        # Get text to compare against
        context_text = ""
        if "content" in context:
            context_text = context["content"]
        elif "title" in context:
            context_text = context["title"]

        context_words = set(context_text.lower().split())

        if not task_words or not context_words:
            return 0.0

        # Jaccard similarity
        intersection = task_words & context_words
        union = task_words | context_words
        return len(intersection) / len(union) if union else 0.0

    def _compute_confidence(self, task: str) -> float:
        """Compute confidence based on prior similar task success."""
        if not self._outcomes:
            return 0.0

        task_words = set(task.lower().split())
        similar_success = 0
        similar_total = 0

        for outcome in self._outcomes:
            prior_task = outcome.get("task", "")
            prior_words = set(prior_task.lower().split())

            # Simple overlap check
            if task_words & prior_words:
                similar_total += 1
                if outcome.get("success", False) and outcome.get("objective_met", False):
                    similar_success += 1

        if similar_total == 0:
            return 0.0

        # Confidence = success rate of similar tasks
        return similar_success / similar_total

    def _is_novel(self, task: str) -> bool:
        """Determine if this task shape has been seen before."""
        if not self._outcomes:
            return True

        task_lower = task.lower()
        for outcome in self._outcomes:
            # Simple check: is this task very similar to any prior?
            prior = outcome.get("task", "").lower()
            # Check if significant word overlap exists
            task_words = set(task_lower.split())
            prior_words = set(prior.split())
            if len(task_words & prior_words) >= min(len(task_words) * 0.5, 3):
                return False

        return True

    def get_context(self, task: str) -> ContextResult:
        """Retrieve context for a given task from local files.

        Args:
            task: The task description

        Returns:
            ContextResult with file contents and computed metadata
        """
        context_files = self._find_context_files()
        contexts = []

        for path in context_files:
            ctx = self._read_context_file(path)
            if ctx.get("type") != "error":
                ctx["_similarity"] = self._compute_similarity(task, ctx)
                contexts.append(ctx)

        # Sort by similarity to task
        contexts.sort(key=lambda x: x.get("_similarity", 0), reverse=True)

        # Take top relevant contexts
        relevant = contexts[:5]
        suggested = [ctx.get("source", "") for ctx in relevant]

        # Build context dictionary
        result_context = {
            "available_files": [str(p) for p in context_files],
            "relevant_contexts": [
                {k: v for k, v in ctx.items() if not k.startswith("_")}
                for ctx in relevant
            ]
        }

        # If we have highly similar context, include it directly
        if relevant and relevant[0].get("_similarity", 0) > 0.3:
            result_context["primary_context"] = {
                k: v for k, v in relevant[0].items() if not k.startswith("_")
            }

        confidence = self._compute_confidence(task)
        coverage = len([c for c in contexts if c.get("_similarity", 0) > 0.1]) / max(len(contexts), 1)
        novel = self._is_novel(task)

        return ContextResult(
            context=result_context,
            confidence=confidence,
            coverage=coverage,
            novel=novel,
            suggested_skills=suggested
        )

    def update(self, task: str, outcome: ExecutionOutcome) -> None:
        """Record execution outcome for learning.

        Args:
            task: The task that was executed
            outcome: The outcome of the execution
        """
        record = {
            "timestamp": datetime.now().isoformat(),
            "task": task,
            "success": outcome.success,
            "objective_met": outcome.objective_met,
            "confidence_delta": outcome.confidence_delta,
            "objective": outcome.objective
        }

        # Append to log file
        try:
            with open(self.outcomes_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            self._outcomes.append(record)
        except IOError:
            # If we can't write, just keep in memory
            self._outcomes.append(record)


class InMemoryContextProvider(ContextProvider):
    """Simple in-memory context provider for testing.

    This provider maintains context entirely in memory and is useful
    for unit tests or simple demonstrations where persistence is not
    required.

    Example:
        ```python
        provider = InMemoryContextProvider()
        provider.set_context({"example": "data"})
        result = provider.get_context("any task")
        ```
    """

    def __init__(self, initial_context: Optional[Dict[str, Any]] = None):
        """Initialize with optional initial context.

        Args:
            initial_context: Starting context dictionary
        """
        self._context = initial_context or {}
        self._outcomes: List[ExecutionOutcome] = []

    def set_context(self, context: Dict[str, Any]) -> None:
        """Set the current context (replaces existing)."""
        self._context = context

    def add_context(self, key: str, value: Any) -> None:
        """Add a key-value pair to the context."""
        self._context[key] = value

    def get_context(self, task: str) -> ContextResult:
        """Return the current in-memory context."""
        # Simple heuristic: more outcomes = higher confidence
        confidence = min(len(self._outcomes) / 10.0, 1.0)
        coverage = 1.0 if self._context else 0.0
        novel = len(self._outcomes) < 3

        return ContextResult(
            context=self._context.copy(),
            confidence=confidence,
            coverage=coverage,
            novel=novel,
            suggested_skills=[]
        )

    def update(self, task: str, outcome: ExecutionOutcome) -> None:
        """Record outcome in memory."""
        self._outcomes.append(outcome)
