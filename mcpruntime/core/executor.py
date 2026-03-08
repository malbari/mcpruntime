"""Policy-aware execution dispatch and sandbox lifecycle management.

This module provides the Executor class which handles execution with
configurable policies based on context confidence levels.
"""

import logging
from enum import Enum
from typing import Any, Dict, Optional, Tuple
from dataclasses import dataclass

from mcpruntime.context.provider import ContextResult, ExecutionOutcome

logger = logging.getLogger(__name__)


class ExecutionMode(Enum):
    """Execution policy mode."""
    CONSERVATIVE = "conservative"
    AUTONOMOUS = "autonomous"


@dataclass
class ExecutionPolicy:
    """Configuration for execution policy.

    Attributes:
        confidence_threshold: Minimum confidence for autonomous mode (0-1)
        max_retries: Maximum retry attempts in conservative mode
        audit_all: Whether to audit log all executions
        require_confirmation: Whether to require human confirmation in conservative mode
    """
    confidence_threshold: float = 0.7
    max_retries: int = 3
    audit_all: bool = True
    require_confirmation: bool = False


class Executor:
    """Policy-aware executor that varies behavior based on context confidence.

    The executor implements the core principle: "autonomy must be earned".
    Execution behavior changes based on epistemic state:

    - Novel or low-confidence tasks → Conservative mode (smaller scope, audit logging)
    - Familiar high-confidence tasks → Autonomous mode (full execution)

    Example:
        ```python
        executor = Executor(confidence_threshold=0.7)
        outcome = executor.run("process_data", context_result)
        ```
    """

    def __init__(
        self,
        confidence_threshold: float = 0.7,
        policy: Optional[ExecutionPolicy] = None,
        sandbox_client: Optional[Any] = None
    ):
        """Initialize the executor.

        Args:
            confidence_threshold: Threshold for autonomous execution (0-1)
            policy: Execution policy configuration
            sandbox_client: Client for sandbox execution
        """
        self.confidence_threshold = confidence_threshold
        self.policy = policy or ExecutionPolicy(confidence_threshold=confidence_threshold)
        self.sandbox_client = sandbox_client
        self._audit_log: list = []

    def _determine_mode(self, context: ContextResult) -> ExecutionMode:
        """Determine execution mode based on context epistemic state.

        Args:
            context: The context result with confidence and novelty metrics

        Returns:
            ExecutionMode.CONSERVATIVE or ExecutionMode.AUTONOMOUS
        """
        if context.novel:
            logger.info("Novel task detected → Conservative mode")
            return ExecutionMode.CONSERVATIVE

        if context.confidence < self.confidence_threshold:
            logger.info(
                f"Low confidence ({context.confidence:.2f} < {self.confidence_threshold:.2f}) "
                "→ Conservative mode"
            )
            return ExecutionMode.CONSERVATIVE

        logger.info(
            f"High confidence ({context.confidence:.2f} >= {self.confidence_threshold:.2f}) "
            "→ Autonomous mode"
        )
        return ExecutionMode.AUTONOMOUS

    def _audit(self, task: str, mode: ExecutionMode, context: ContextResult) -> None:
        """Log execution decision for audit trail."""
        entry = {
            "task": task,
            "mode": mode.value,
            "confidence": context.confidence,
            "coverage": context.coverage,
            "novel": context.novel,
        }
        self._audit_log.append(entry)

        if self.policy.audit_all:
            logger.info(f"[AUDIT] {task}: {mode.value} mode (confidence={context.confidence:.2f})")

    def _run_conservative(
        self,
        task: str,
        context: ContextResult,
        code: Optional[str] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """Execute in conservative mode with safety constraints.

        Conservative mode features:
        - Smaller execution scope
        - Verbose audit logging
        - Optional human confirmation
        - Limited retries

        Args:
            task: Task description
            context: Context result
            code: Optional pre-generated code

        Returns:
            Tuple of (success, output, error)
        """
        logger.info(f"[CONSERVATIVE] Executing: {task[:100]}...")

        if self.policy.require_confirmation:
            # In a real implementation, this would prompt for confirmation
            logger.warning("Human confirmation required but not implemented")

        # Limit execution scope in conservative mode
        timeout = 30  # Shorter timeout
        max_memory = 128  # Lower memory limit

        try:
            if self.sandbox_client:
                result = self.sandbox_client.execute(
                    code or task,
                    timeout=timeout,
                    max_memory=max_memory,
                    context=context.context
                )
                success = result.get("success", False)
                output = result.get("output", "")
                error = result.get("error")
            else:
                # Fallback without sandbox
                if code:
                    # Local execution would go here
                    success, output, error = False, "", "No sandbox configured"
                else:
                    success, output, error = False, "", "No code provided and no sandbox"

            return success, output, error

        except Exception as e:
            logger.error(f"[CONSERVATIVE] Execution failed: {e}")
            return False, "", str(e)

    def _run_autonomous(
        self,
        task: str,
        context: ContextResult,
        code: Optional[str] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """Execute in autonomous mode with full capabilities.

        Autonomous mode features:
        - Full PTC (Programmatic Tool Calling) execution
        - Complete access to skill registry
        - Standard resource limits

        Args:
            task: Task description
            context: Context result
            code: Optional pre-generated code

        Returns:
            Tuple of (success, output, error)
        """
        logger.info(f"[AUTONOMOUS] Executing: {task[:100]}...")

        try:
            if self.sandbox_client:
                result = self.sandbox_client.execute(
                    code or task,
                    context=context.context,
                    skills=context.suggested_skills
                )
                success = result.get("success", False)
                output = result.get("output", "")
                error = result.get("error")
            else:
                success, output, error = False, "", "No sandbox configured"

            return success, output, error

        except Exception as e:
            logger.error(f"[AUTONOMOUS] Execution failed: {e}")
            return False, "", str(e)

    def run(
        self,
        task: str,
        context: ContextResult,
        code: Optional[str] = None
    ) -> ExecutionOutcome:
        """Execute a task with policy-aware behavior.

        This is the main entry point for execution. Behavior varies based on
        confidence and novelty metrics in the context.

        Args:
            task: Task description or goal
            context: Context result from a ContextProvider
            code: Optional pre-generated code to execute

        Returns:
            ExecutionOutcome with results and metadata
        """
        mode = self._determine_mode(context)
        self._audit(task, mode, context)

        if mode == ExecutionMode.CONSERVATIVE:
            success, output, error = self._run_conservative(task, context, code)
        else:
            success, output, error = self._run_autonomous(task, context, code)

        # Compute confidence delta (simplified heuristic)
        confidence_delta = 0.1 if success else -0.1

        # Determine if objective was met (simplified)
        objective_met = success and not error

        outcome = ExecutionOutcome(
            success=success,
            objective_met=objective_met,
            confidence_delta=confidence_delta,
            task=task,
            objective=output[:200] if output else ""
        )

        return outcome

    def get_audit_log(self) -> list:
        """Get the audit log of all execution decisions."""
        return self._audit_log.copy()
