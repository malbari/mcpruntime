"""Skill extractor for promoting successful executions to skills.

This module provides functionality to automatically extract working
code actions and convert them into reusable skills.
"""

import ast
import logging
import re
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from mcpruntime.skills.registry import SkillRegistry, Skill

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Result of skill extraction.

    Attributes:
        success: Whether extraction succeeded
        skill: Extracted skill (if successful)
        reason: Explanation if extraction failed
    """
    success: bool
    skill: Optional[Skill] = None
    reason: str = ""


class SkillExtractor:
    """Extracts skills from successful code executions.

    The extractor analyzes executed code and determines if it represents
    a reusable solution worth preserving as a skill.

    Attributes:
        registry: Skill registry to save extracted skills
        min_code_lines: Minimum lines of code for extraction
        max_code_lines: Maximum lines of code for extraction

    Example:
        ```python
        extractor = SkillExtractor(registry)
        result = extractor.extract(task, code, output, error)
        if result.success:
            print(f"Extracted skill: {result.skill.name}")
        ```
    """

    def __init__(
        self,
        registry: SkillRegistry,
        min_code_lines: int = 5,
        max_code_lines: int = 200
    ):
        """Initialize the skill extractor.

        Args:
            registry: Skill registry to save to
            min_code_lines: Minimum code length for extraction
            max_code_lines: Maximum code length for extraction
        """
        self.registry = registry
        self.min_code_lines = min_code_lines
        self.max_code_lines = max_code_lines

    def _is_valid_python(self, code: str) -> bool:
        """Check if code is syntactically valid Python."""
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False

    def _extract_functions(self, code: str) -> List[ast.FunctionDef]:
        """Extract function definitions from code."""
        try:
            tree = ast.parse(code)
            return [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        except SyntaxError:
            return []

    def _generate_skill_name(self, task: str, code: str) -> str:
        """Generate a skill name from task and code."""
        # Try to extract from task description
        task_lower = task.lower()

        # Common patterns
        if "fetch" in task_lower or "get" in task_lower:
            return "fetch_data"
        if "process" in task_lower or "transform" in task_lower:
            return "process_data"
        if "analyze" in task_lower:
            return "analyze_data"
        if "calculate" in task_lower:
            return "calculate"

        # Generate from first function name if available
        funcs = self._extract_functions(code)
        if funcs:
            return funcs[0].name

        # Fallback: use first few words of task
        words = re.findall(r'\b[a-zA-Z]+\b', task_lower)[:3]
        return "_".join(words) if words else "skill"

    def _generate_description(self, task: str, code: str) -> str:
        """Generate a description from task and code."""
        # Use task as base description
        desc = task.strip()
        if len(desc) > 100:
            desc = desc[:97] + "..."
        return desc

    def _infer_signature(self, code: str, func_name: str = "run") -> str:
        """Infer function signature from code."""
        funcs = self._extract_functions(code)
        for func in funcs:
            if func.name == func_name:
                args = [arg.arg for arg in func.args.args]
                return f"({', '.join(args)})"
        return "()"

    def _is_worth_preserving(
        self,
        code: str,
        output: str,
        error: Optional[str]
    ) -> tuple[bool, str]:
        """Determine if code is worth preserving as a skill.

        Returns:
            Tuple of (worth_preserving, reason)
        """
        # Must have succeeded
        if error:
            return False, "Execution had errors"

        # Check code length
        lines = code.strip().split('\n')
        line_count = len([l for l in lines if l.strip()])

        if line_count < self.min_code_lines:
            return False, f"Too short ({line_count} lines < {self.min_code_lines})"

        if line_count > self.max_code_lines:
            return False, f"Too long ({line_count} lines > {self.max_code_lines})"

        # Must be valid Python
        if not self._is_valid_python(code):
            return False, "Invalid Python syntax"

        # Must have at least one function or substantial logic
        funcs = self._extract_functions(code)
        if not funcs and line_count < 10:
            return False, "No function definitions and too short"

        # Check output quality (must have produced something)
        if not output or len(output.strip()) < 5:
            return False, "No meaningful output produced"

        return True, "Code appears to be a valid, useful solution"

    def extract(
        self,
        task: str,
        code: str,
        output: str,
        error: Optional[str] = None,
        auto_save: bool = False
    ) -> ExtractionResult:
        """Attempt to extract a skill from executed code.

        Args:
            task: Original task description
            code: Executed code
            output: Execution output
            error: Execution error (if any)
            auto_save: Whether to automatically save to registry

        Returns:
            ExtractionResult indicating success and skill details
        """
        worth_it, reason = self._is_worth_preserving(code, output, error)

        if not worth_it:
            return ExtractionResult(success=False, reason=reason)

        # Generate skill metadata
        name = self._generate_skill_name(task, code)
        description = self._generate_description(task, code)
        signature = self._infer_signature(code)

        # Wrap in skill structure if not already
        skill_code = self._wrap_as_skill(code, name)

        skill = Skill(
            name=name,
            description=description,
            code=skill_code,
            entry_point="run",
            signature=signature
        )

        if auto_save:
            try:
                self.registry.save_skill(
                    name=name,
                    code=skill_code,
                    description=description,
                    entry_point="run",
                    signature=signature
                )
            except Exception as e:
                return ExtractionResult(
                    success=False,
                    reason=f"Failed to save skill: {e}"
                )

        return ExtractionResult(success=True, skill=skill, reason=reason)

    def _wrap_as_skill(self, code: str, name: str) -> str:
        """Wrap code in a skill module structure.

        Args:
            code: Original code
            name: Skill name

        Returns:
            Wrapped skill code
        """
        lines = [
            f'"""Skill: {name}"""',
            "",
            code,
            "",
            "# Skill entry point (if no explicit run function)",
            "if __name__ == '__main__':",
            "    result = run() if 'run' in dir() else None",
            "    if result:",
            "        print(result)",
        ]

        return "\n".join(lines)

    def suggest_skill_name(self, task: str) -> str:
        """Suggest a skill name for a task (before execution).

        Args:
            task: Task description

        Returns:
            Suggested skill name
        """
        return self._generate_skill_name(task, "")
