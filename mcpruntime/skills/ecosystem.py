"""Ecosystem-level metrics for skill libraries.

Tracks the emergent growth curve showing when compositional structure
begins to dominate over new skill generation.
"""

import json
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, List, Dict, Optional, Tuple

from mcpruntime.skills.registry import SkillRegistry
from mcpruntime.skills.composer import CompositionPattern


@dataclass
class GrowthSnapshot:
    """Single point on the skill library growth curve.
    
    This is the key data structure for the paper's main figure:
    X axis: task_number
    Y axis: composition_rate
    """
    task_number: int
    timestamp: str
    
    # Skill counts
    total_skills: int
    skills_created_this_task: int = 0
    
    # Composition metrics
    total_compositions: int = 0
    compositions_used_this_task: int = 0
    composition_rate: float = 0.0  # % of this task solved via composition
    
    # Breakdown of how task was solved
    via_new_skill: bool = False
    via_existing_skill: bool = False
    via_composition: bool = False
    
    # Diversity (Shannon entropy of skill categories)
    skill_diversity: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class InflectionPoint:
    """Detected inflection where composition begins to dominate."""
    task_number: int
    composition_rate: float
    threshold: float
    confidence: float


@dataclass
class EcosystemHealth:
    """Overall health metrics for the skill ecosystem."""
    total_skills: int
    total_compositions: int
    avg_reuse_rate: float  # Times each skill is reused
    composition_coverage: float  # % of tasks using compositions
    diversity_index: float  # Shannon entropy
    growth_rate: float  # Skills per task (should decrease over time)
    
    # Key paper metric
    composition_dominance: float  # % of recent tasks using composition


class EcosystemTracker:
    """Tracks skill ecosystem evolution over task sequences.
    
    Produces the paper's main figure:
    - X: Tasks solved (1 → 300)
    - Y: % solved by composition vs new skill generation
    - The inflection point where composition > 50% is the key finding
    """
    
    def __init__(
        self,
        skill_registry: SkillRegistry,
        composition_miner: Any = None,
        log_dir: str = "./results/ecosystem"
    ):
        """Initialize tracker.
        
        Args:
            skill_registry: Registry to track
            composition_miner: Miner for discovering compositions
            log_dir: Where to write growth curve logs
        """
        self.registry = skill_registry
        self.composition_miner = composition_miner
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.snapshots: List[GrowthSnapshot] = []
        self.compositions: List[CompositionPattern] = []
        self.execution_logs: List[Dict] = []
        
    def record_task(
        self,
        task_number: int,
        skills_used: List[str],
        skills_created: List[str],
        compositions_used: List[str],
        success: bool
    ) -> GrowthSnapshot:
        """Record metrics after each task.
        
        This is called after every task execution to build the growth curve.
        """
        # Calculate rates
        total_methods = len(skills_used) + len(compositions_used)
        composition_rate = (
            len(compositions_used) / total_methods
            if total_methods > 0 else 0.0
        )
        
        # Determine how task was solved
        via_composition = len(compositions_used) > 0
        via_existing = len(skills_used) > 0 and not skills_created
        via_new = len(skills_created) > 0
        
        # Calculate diversity
        diversity = self._compute_diversity()
        
        snapshot = GrowthSnapshot(
            task_number=task_number,
            timestamp=datetime.now().isoformat(),
            total_skills=len(self.registry.list_skills()),
            skills_created_this_task=len(skills_created),
            total_compositions=len(self.compositions),
            compositions_used_this_task=len(compositions_used),
            composition_rate=composition_rate,
            via_new_skill=via_new,
            via_existing_skill=via_existing,
            via_composition=via_composition,
            skill_diversity=diversity
        )
        
        self.snapshots.append(snapshot)
        
        # Periodically mine compositions (every 50 tasks)
        if task_number % 50 == 0 and self.composition_miner:
            self._update_compositions()
        
        return snapshot
    
    def _update_compositions(self):
        """Mine compositions from accumulated execution logs."""
        if not self.composition_miner:
            return
            
        new_patterns = self.composition_miner.mine_compositions(
            self.execution_logs,
            self.registry
        )
        
        # Add new patterns
        existing_keys = {
            f"{p.source_skill}→{p.target_skill}"
            for p in self.compositions
        }
        
        for pattern in new_patterns:
            key = f"{pattern.source_skill}→{pattern.target_skill}"
            if key not in existing_keys:
                self.compositions.append(pattern)
    
    def detect_inflection_point(
        self,
        threshold: float = 0.5,
        window_size: int = 10
    ) -> Optional[InflectionPoint]:
        """Detect where composition rate crosses threshold.
        
        This is the paper's key finding: the task number where
        composition begins to dominate (>50% of solutions).
        
        Args:
            threshold: Composition rate threshold (default 0.5)
            window_size: Number of consecutive tasks above threshold
            
        Returns:
            InflectionPoint if found, None otherwise
        """
        if len(self.snapshots) < window_size:
            return None
        
        for i in range(len(self.snapshots) - window_size + 1):
            window = self.snapshots[i:i + window_size]
            rates = [s.composition_rate for s in window]
            
            # Check if all rates in window are above threshold
            if all(r >= threshold for r in rates):
                # Found inflection
                mid_point = window[len(window) // 2]
                return InflectionPoint(
                    task_number=mid_point.task_number,
                    composition_rate=mid_point.composition_rate,
                    threshold=threshold,
                    confidence=self._compute_inflection_confidence(window)
                )
        
        return None
    
    def _compute_inflection_confidence(
        self,
        window: List[GrowthSnapshot]
    ) -> float:
        """Compute confidence that this is a real inflection."""
        # Higher confidence if rates are consistently high
        rates = [s.composition_rate for s in window]
        avg_rate = sum(rates) / len(rates)
        variance = sum((r - avg_rate) ** 2 for r in rates) / len(rates)
        
        # Lower variance = higher confidence
        return min(avg_rate * (1 - variance), 1.0)
    
    def get_ecosystem_health(self, recent_n: int = 50) -> EcosystemHealth:
        """Compute overall ecosystem health metrics."""
        skills = self.registry.list_skills()
        
        # Compute reuse rate
        total_usage = sum(s.usage_count for s in skills)
        avg_reuse = total_usage / len(skills) if skills else 0
        
        # Compute composition coverage from recent snapshots
        recent = self.snapshots[-recent_n:] if len(self.snapshots) > recent_n else self.snapshots
        composition_coverage = (
            sum(1 for s in recent if s.via_composition) / len(recent)
            if recent else 0
        )
        
        # Growth rate (skills per task in recent window)
        recent_skills = sum(s.skills_created_this_task for s in recent)
        growth_rate = recent_skills / len(recent) if recent else 0
        
        # Composition dominance in recent tasks
        composition_dominance = (
            sum(s.composition_rate for s in recent) / len(recent)
            if recent else 0
        )
        
        return EcosystemHealth(
            total_skills=len(skills),
            total_compositions=len(self.compositions),
            avg_reuse_rate=avg_reuse,
            composition_coverage=composition_coverage,
            diversity_index=self._compute_diversity(),
            growth_rate=growth_rate,
            composition_dominance=composition_dominance
        )
    
    def _compute_diversity(self) -> float:
        """Compute Shannon diversity index of skill categories."""
        skills = self.registry.list_skills()
        if not skills:
            return 0.0
        
        # Count by category/tag
        categories: Dict[str, int] = {}
        for skill in skills:
            for tag in skill.tags:
                categories[tag] = categories.get(tag, 0) + 1
        
        if not categories:
            return 0.0
        
        # Shannon entropy
        total = len(skills)
        entropy = -sum(
            (count / total) * math.log2(count / total)
            for count in categories.values()
        )
        
        return entropy
    
    def export_growth_curve(self, path: Optional[str] = None) -> str:
        """Export growth curve data for plotting.
        
        Returns JSON with the main figure data:
        {
            "tasks": [1, 2, 3, ...],
            "composition_rates": [0.0, 0.1, 0.5, ...],
            "new_skill_rates": [1.0, 0.9, 0.5, ...],
            "inflection_point": {"task_number": 150, ...}
        }
        """
        if path is None:
            path = self.log_dir / "growth_curve.json"
        
        data = {
            "tasks": [s.task_number for s in self.snapshots],
            "composition_rates": [s.composition_rate for s in self.snapshots],
            "new_skill_rates": [
                1.0 - s.composition_rate for s in self.snapshots
            ],
            "total_skills": [s.total_skills for s in self.snapshots],
            "diversity": [s.skill_diversity for s in self.snapshots],
        }
        
        inflection = self.detect_inflection_point()
        if inflection:
            data["inflection_point"] = {
                "task_number": inflection.task_number,
                "composition_rate": inflection.composition_rate,
                "threshold": inflection.threshold,
                "confidence": inflection.confidence
            }
        
        health = self.get_ecosystem_health()
        data["ecosystem_health"] = {
            "total_skills": health.total_skills,
            "total_compositions": health.total_compositions,
            "composition_dominance": health.composition_dominance,
            "diversity_index": health.diversity_index
        }
        
        Path(path).write_text(json.dumps(data, indent=2))
        return str(path)
    
    def get_summary_statistics(self) -> Dict:
        """Get summary stats for paper."""
        if not self.snapshots:
            return {}
        
        # Early vs late comparison
        early = self.snapshots[:50] if len(self.snapshots) >= 50 else self.snapshots[:len(self.snapshots)//3]
        late = self.snapshots[-50:] if len(self.snapshots) >= 50 else self.snapshots[-len(self.snapshots)//3:]
        
        early_comp = sum(s.composition_rate for s in early) / len(early) if early else 0
        late_comp = sum(s.composition_rate for s in late) / len(late) if late else 0
        
        early_growth = sum(s.skills_created_this_task for s in early) / len(early) if early else 0
        late_growth = sum(s.skills_created_this_task for s in late) / len(late) if late else 0
        
        return {
            "total_tasks": len(self.snapshots),
            "early_phase": {
                "composition_rate": early_comp,
                "skills_per_task": early_growth
            },
            "late_phase": {
                "composition_rate": late_comp,
                "skills_per_task": late_growth
            },
            "emergence_ratio": late_comp / early_comp if early_comp > 0 else float('inf'),
            "growth_reduction": early_growth / late_growth if late_growth > 0 else float('inf'),
            "inflection_detected": self.detect_inflection_point() is not None
        }
