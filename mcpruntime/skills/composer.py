"""Composition discovery from execution traces.

This module mines execution logs to discover compositional patterns between
skills, enabling emergent tool ecosystems without explicit programming.
"""

import ast
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple, Any
from pathlib import Path

from mcpruntime.skills.registry import Skill


@dataclass
class CompositionPattern:
    """A discovered composition pattern between skills."""
    source_skill: str  # Skill that comes first
    target_skill: str  # Skill that comes second (or "_new_" for augmentation)
    composition_type: str  # "sequential", "augmented", "conditional"
    context_code: str  # Code surrounding the composition
    frequency: int = 1  # How many times seen
    task_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0  # Generalization confidence


@dataclass
class ValidationResult:
    """Result of validating a composition on held-out tasks."""
    composition: CompositionPattern
    tasks_tested: int
    tasks_succeeded: int
    success_rate: float
    vs_llm_generated: float  # How much better than LLM-generated composition


class CompositionMiner:
    """Mines execution traces for latent compositional structure.
    
    Key insight: When an agent solves task B by using skill A plus additional
    code, that's evidence for a valid A→B composition.
    
    Example:
        Task SE01: "Sum a list" → Extract skill: sum_list()
        Task SE02: "Average a list" → Uses sum_list() + division
        
        System discovers: sum_list → (divide by len) = average_list
    """
    
    def __init__(self, min_frequency: int = 2):
        """Initialize miner.
        
        Args:
            min_frequency: Minimum times a pattern must be seen to be considered
        """
        self.min_frequency = min_frequency
        self.patterns: Dict[str, CompositionPattern] = {}
        
    def mine_compositions(
        self,
        execution_logs: List[Dict[str, Any]],
        skill_registry: Optional[Any] = None
    ) -> List[CompositionPattern]:
        """Mine execution logs for compositional patterns.
        
        Args:
            execution_logs: List of execution records with keys:
                - task_id: str
                - code: str (executed code)
                - skills_used: List[str] (skills imported)
                - success: bool
                - output: Any
            skill_registry: SkillRegistry to check available skills
            
        Returns:
            List of discovered composition patterns sorted by confidence
        """
        # Extract patterns from each execution
        for log in execution_logs:
            if not log.get("success", False):
                continue
                
            patterns = self._extract_patterns_from_execution(log, skill_registry)
            for pattern in patterns:
                key = f"{pattern.source_skill}→{pattern.target_skill}"
                if key in self.patterns:
                    self.patterns[key].frequency += 1
                    self.patterns[key].task_ids.append(log["task_id"])
                else:
                    self.patterns[key] = pattern
                    pattern.task_ids = [log["task_id"]]
        
        # Filter by frequency and compute confidence
        validated = [
            p for p in self.patterns.values()
            if p.frequency >= self.min_frequency
        ]
        
        for pattern in validated:
            pattern.confidence = self._compute_confidence(pattern)
        
        return sorted(validated, key=lambda p: p.confidence, reverse=True)
    
    def _extract_patterns_from_execution(
        self,
        log: Dict[str, Any],
        skill_registry: Optional[Any]
    ) -> List[CompositionPattern]:
        """Extract composition patterns from a single execution."""
        patterns = []
        code = log.get("code", "")
        skills_used = log.get("skills_used", [])
        
        if not skills_used or len(skills_used) < 1:
            return patterns
        
        # Parse code to find skill usage patterns
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return patterns
        
        # Look for sequential patterns: skill_a -> skill_b
        patterns.extend(self._find_sequential_patterns(tree, skills_used))
        
        # Look for augmented patterns: skill_a + transformation
        patterns.extend(self._find_augmented_patterns(tree, skills_used, code))
        
        return patterns
    
    def _find_sequential_patterns(
        self,
        tree: ast.AST,
        skills_used: List[str]
    ) -> List[CompositionPattern]:
        """Find sequential skill usage patterns."""
        patterns = []
        
        # Find all function calls
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        ]
        
        # Check for data flow between calls
        for i, call in enumerate(calls[:-1]):
            next_call = calls[i + 1]
            
            # Check if output of call could flow into next_call
            if self._has_data_flow(call, next_call, tree):
                # Try to extract skill names from calls
                source = self._extract_skill_name(call, skills_used)
                target = self._extract_skill_name(next_call, skills_used)
                
                if source and target and source != target:
                    patterns.append(CompositionPattern(
                        source_skill=source,
                        target_skill=target,
                        composition_type="sequential",
                        context_code=ast.unparse(call)[:100]
                    ))
        
        return patterns
    
    def _find_augmented_patterns(
        self,
        tree: ast.AST,
        skills_used: List[str],
        full_code: str
    ) -> List[CompositionPattern]:
        """Find patterns where a skill is augmented with additional logic."""
        patterns = []
        
        # Look for function definitions that use skills
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_code = ast.unparse(node)
                used_in_func = [
                    s for s in skills_used
                    if s in func_code
                ]
                
                if used_in_func:
                    # This function augments a skill
                    for skill in used_in_func:
                        # Extract what was added
                        augmentation = self._extract_augmentation(node, skill)
                        if augmentation:
                            patterns.append(CompositionPattern(
                                source_skill=skill,
                                target_skill=f"_new_{node.name}",
                                composition_type="augmented",
                                context_code=augmentation[:100]
                            ))
        
        return patterns
    
    def _has_data_flow(
        self,
        source: ast.Call,
        target: ast.Call,
        tree: ast.AST
    ) -> bool:
        """Check if data likely flows from source call to target call."""
        # Simple heuristic: check if target uses a variable that source could define
        source_lineno = getattr(source, 'lineno', 0)
        target_lineno = getattr(target, 'lineno', 0)
        
        # Must be sequential in code
        if target_lineno <= source_lineno:
            return False
        
        # Check if they're in same function/block
        source_scope = self._get_scope(source, tree)
        target_scope = self._get_scope(target, tree)
        
        return source_scope == target_scope
    
    def _extract_skill_name(
        self,
        call: ast.Call,
        skills_used: List[str]
    ) -> Optional[str]:
        """Extract which skill a call corresponds to."""
        func_name = self._get_call_name(call)
        if not func_name:
            return None
        
        # Match against skills used
        for skill in skills_used:
            if skill in func_name or func_name in skill:
                return skill
        
        return None
    
    def _get_call_name(self, call: ast.Call) -> Optional[str]:
        """Get function name from a call node."""
        if isinstance(call.func, ast.Name):
            return call.func.id
        elif isinstance(call.func, ast.Attribute):
            return call.func.attr
        return None
    
    def _get_scope(self, node: ast.AST, tree: ast.AST) -> Optional[ast.AST]:
        """Get the enclosing function/class for a node."""
        for parent in ast.walk(tree):
            if isinstance(parent, (ast.FunctionDef, ast.ClassDef)):
                for child in ast.walk(parent):
                    if child is node:
                        return parent
        return tree
    
    def _extract_augmentation(
        self,
        func: ast.FunctionDef,
        skill_name: str
    ) -> str:
        """Extract what logic augments the skill in a function."""
        func_code = ast.unparse(func)
        
        # Remove the skill call itself, keep surrounding logic
        lines = func_code.split('\n')
        augmentation = []
        
        for line in lines:
            if skill_name in line:
                continue  # Skip the skill call
            if line.strip() and not line.strip().startswith('#'):
                augmentation.append(line.strip())
        
        return '\n'.join(augmentation[:5])  # First 5 non-skill lines
    
    def _compute_confidence(self, pattern: CompositionPattern) -> float:
        """Compute confidence score for a pattern."""
        # Base confidence from frequency
        freq_score = min(pattern.frequency / 10, 1.0)
        
        # Type-specific bonuses
        type_bonus = {
            "sequential": 0.1,
            "augmented": 0.15,  # Augmented patterns are stronger
            "conditional": 0.05
        }.get(pattern.composition_type, 0)
        
        return min(freq_score + type_bonus, 1.0)
    
    def validate_composition(
        self,
        pattern: CompositionPattern,
        test_tasks: List[Any],
        executor: Any,
        llm_generator: Any
    ) -> ValidationResult:
        """Validate a discovered composition against held-out tasks.
        
        Critical for paper: Show mined compositions generalize better
        than LLM-generated compositions on the same tasks.
        """
        tasks_tested = len(test_tasks)
        tasks_succeeded = 0
        llm_succeeded = 0
        
        for task in test_tasks:
            # Test discovered composition
            discovered_result = self._test_with_composition(
                task, pattern, executor
            )
            if discovered_result:
                tasks_succeeded += 1
            
            # Test LLM-generated composition for comparison
            llm_result = self._test_with_llm_composition(
                task, pattern, llm_generator, executor
            )
            if llm_result:
                llm_succeeded += 1
        
        success_rate = tasks_succeeded / tasks_tested if tasks_tested else 0
        llm_rate = llm_succeeded / tasks_tested if tasks_tested else 0
        
        return ValidationResult(
            composition=pattern,
            tasks_tested=tasks_tested,
            tasks_succeeded=tasks_succeeded,
            success_rate=success_rate,
            vs_llm_generated=(success_rate - llm_rate)
        )
    
    def _test_with_composition(
        self,
        task: Any,
        pattern: CompositionPattern,
        executor: Any
    ) -> bool:
        """Test task using discovered composition."""
        # Generate code using the composition
        code = self._generate_composition_code(pattern, task)
        
        # Execute and check success
        result, output, error = executor.execute(code)
        return error is None and output
    
    def _test_with_llm_composition(
        self,
        task: Any,
        pattern: CompositionPattern,
        llm_generator: Any,
        executor: Any
    ) -> bool:
        """Test task using LLM-generated composition."""
        # Ask LLM to compose the same skills
        prompt = f"""
        Create a solution for: {task.description}
        
        Use these skills together:
        - {pattern.source_skill}
        - {pattern.target_skill if pattern.target_skill != '_new_' else 'additional logic'}
        
        Generate Python code that composes them.
        """
        
        code = llm_generator.generate(prompt)
        result, output, error = executor.execute(code)
        return error is None and output
    
    def _generate_composition_code(
        self,
        pattern: CompositionPattern,
        task: Any
    ) -> str:
        """Generate code implementing a composition pattern."""
        if pattern.composition_type == "sequential":
            return f"""
from skills.{pattern.source_skill} import run as step1
from skills.{pattern.target_skill} import run as step2

# Sequential composition discovered from execution
data = task_input()
intermediate = step1(data)
result = step2(intermediate)
print(result)
"""
        elif pattern.composition_type == "augmented":
            return f"""
from skills.{pattern.source_skill} import run as base_func

# Augmented composition
data = task_input()
base_result = base_func(data)
# Additional transformation from context:
{pattern.context_code}
"""
        else:
            return f"""
# Composition: {pattern.source_skill} → {pattern.target_skill}
from skills.{pattern.source_skill} import run
print(run(task_input()))
"""
