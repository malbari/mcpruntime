"""
SkillsBench Integration for MCPRuntime

This module provides integration with SkillsBench (arxiv 2602.12670) to evaluate
MCPRuntime's execution-grounded skill evolution as a 4th condition alongside
the original 3 conditions:
1. No skills (baseline)
2. Curated skills (human-written)
3. Self-generated skills (speculation-based)
4. Runtime-evolved skills (execution-grounded) <- MCPRuntime's contribution

The key distinction:
- Self-generated skills: Created BEFORE task execution (speculation)
- Runtime-evolved skills: Created AFTER successful execution (grounded in working code)

This allows direct empirical comparison showing why execution-grounded skill
evolution succeeds where speculation-based generation fails.
"""

from .loader import SkillsBenchLoader
from .runner import SkillsBenchRunner
from .skill_conditions import SkillCondition, ConditionManager
from .metrics import SkillsBenchMetrics, SkillEcosystemMetrics

__all__ = [
    "SkillsBenchLoader",
    "SkillsBenchRunner",
    "SkillCondition",
    "ConditionManager",
    "SkillsBenchMetrics",
    "SkillEcosystemMetrics",
]
