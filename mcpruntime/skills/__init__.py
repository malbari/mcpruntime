"""Skills layer for MCPRuntime.

This module contains the self-growing tool library with emergent
compositional structure discovery.

- registry: Skill storage and discovery
- extractor: Promotes successful executions to skills
- composer: Discovers compositional patterns from execution traces
- ecosystem: Tracks emergent growth curves and inflection points

Skills accumulate over time and begin to compose as the library grows,
creating sustainable performance advantages through execution-grounded
evolution.
"""

from mcpruntime.skills.registry import SkillRegistry, Skill
from mcpruntime.skills.extractor import SkillExtractor, ExtractionResult
from mcpruntime.skills.composer import (
    CompositionMiner,
    CompositionPattern,
    ValidationResult,
)
from mcpruntime.skills.ecosystem import (
    EcosystemTracker,
    GrowthSnapshot,
    InflectionPoint,
    EcosystemHealth,
)

__all__ = [
    "SkillRegistry",
    "Skill",
    "SkillExtractor",
    "ExtractionResult",
    "CompositionMiner",
    "CompositionPattern",
    "ValidationResult",
    "EcosystemTracker",
    "GrowthSnapshot",
    "InflectionPoint",
    "EcosystemHealth",
]
