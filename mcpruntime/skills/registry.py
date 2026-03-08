"""Skill storage and discovery for the self-growing tool library.

This module provides the SkillRegistry for storing, discovering, and
managing skills that accumulate over time.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """A skill in the registry.

    Attributes:
        name: Unique skill identifier
        description: What the skill does
        code: The skill source code
        entry_point: Function name to call (default: "run")
        signature: Type signature string
        tags: Classification tags
        created_at: When the skill was created
        usage_count: How many times this skill has been used
        success_count: How many successful executions
    """
    name: str
    description: str
    code: str
    entry_point: str = "run"
    signature: str = ""
    tags: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    usage_count: int = 0
    success_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Skill":
        """Create from dictionary representation."""
        return cls(**data)


class SkillRegistry:
    """Registry for storing and discovering skills.

    The skill registry maintains a collection of reusable skills that
grow over time as the system learns from successful executions.

    Attributes:
        skills_dir: Directory where skills are stored
        index_file: Path to skill index JSON file

    Example:
        ```python
        registry = SkillRegistry("./skills")
        registry.save_skill("fetch_data", code, description)
        skills = registry.find_skills("data retrieval")
        ```
    """

    def __init__(
        self,
        skills_dir: str = "./skills",
        index_file: str = "./skills/skill_index.json"
    ):
        """Initialize the skill registry.

        Args:
            skills_dir: Directory to store skill files
            index_file: Path to skill index
        """
        self.skills_dir = Path(skills_dir)
        self.index_file = Path(index_file)
        self._skills: Dict[str, Skill] = {}
        self._index: Dict[str, Any] = {}

        self._ensure_directories()
        self._load_index()
        self._load_skills()

    def _ensure_directories(self) -> None:
        """Ensure required directories exist."""
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def _load_index(self) -> None:
        """Load the skill index from disk."""
        if self.index_file.exists():
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    self._index = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load skill index: {e}")
                self._index = {"version": 1, "skills": {}}
        else:
            self._index = {"version": 1, "skills": {}}

    def _save_index(self) -> None:
        """Save the skill index to disk."""
        try:
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump(self._index, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save skill index: {e}")

    def _load_skills(self) -> None:
        """Load all skills from disk."""
        if not self.skills_dir.exists():
            return

        for skill_file in self.skills_dir.glob("*.py"):
            name = skill_file.stem
            try:
                code = skill_file.read_text(encoding="utf-8")

                # Get metadata from index if available
                meta = self._index.get("skills", {}).get(name, {})

                self._skills[name] = Skill(
                    name=name,
                    description=meta.get("description", f"Skill: {name}"),
                    code=code,
                    entry_point=meta.get("entry_point", "run"),
                    signature=meta.get("signature", ""),
                    tags=meta.get("tags", []),
                    created_at=meta.get("created_at", datetime.now().isoformat()),
                    usage_count=meta.get("usage_count", 0),
                    success_count=meta.get("success_count", 0)
                )
            except IOError as e:
                logger.warning(f"Failed to load skill {name}: {e}")

    def save_skill(
        self,
        name: str,
        code: str,
        description: str = "",
        entry_point: str = "run",
        signature: str = "",
        tags: Optional[List[str]] = None
    ) -> Skill:
        """Save a new skill to the registry.

        Args:
            name: Skill name (used as filename)
            code: Python source code
            description: What the skill does
            entry_point: Function name to call
            signature: Type signature
            tags: Classification tags

        Returns:
            The saved Skill object
        """
        # Sanitize name for filesystem
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)

        skill = Skill(
            name=safe_name,
            description=description,
            code=code,
            entry_point=entry_point,
            signature=signature,
            tags=tags or []
        )

        # Save code to file
        skill_file = self.skills_dir / f"{safe_name}.py"
        try:
            skill_file.write_text(code, encoding="utf-8")
        except IOError as e:
            logger.error(f"Failed to save skill file: {e}")
            raise

        # Update index
        self._index.setdefault("skills", {})[safe_name] = {
            "description": description,
            "entry_point": entry_point,
            "signature": signature,
            "tags": tags or [],
            "created_at": skill.created_at,
            "usage_count": 0,
            "success_count": 0
        }
        self._save_index()

        # Update in-memory cache
        self._skills[safe_name] = skill

        logger.info(f"Saved skill: {safe_name}")
        return skill

    def get_skill(self, name: str) -> Optional[Skill]:
        """Get a skill by name.

        Args:
            name: Skill name

        Returns:
            Skill if found, None otherwise
        """
        return self._skills.get(name)

    def list_skills(self) -> List[Skill]:
        """List all registered skills.

        Returns:
            List of all skills
        """
        return list(self._skills.values())

    def find_skills(self, query: str, limit: int = 10) -> List[Skill]:
        """Find skills matching a query.

        Args:
            query: Search query string
            limit: Maximum results to return

        Returns:
            List of matching skills sorted by relevance
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        scored = []
        for skill in self._skills.values():
            score = 0

            # Check name match
            if query_lower in skill.name.lower():
                score += 10

            # Check description match
            if skill.description and query_lower in skill.description.lower():
                score += 5

            # Check tag match
            for tag in skill.tags:
                if query_lower in tag.lower():
                    score += 3

            # Check word overlap
            desc_words = set(skill.description.lower().split()) if skill.description else set()
            overlap = query_words & desc_words
            score += len(overlap)

            if score > 0:
                scored.append((score, skill))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        return [skill for _, skill in scored[:limit]]

    def record_usage(self, name: str, success: bool) -> None:
        """Record that a skill was used.

        Args:
            name: Skill name
            success: Whether execution was successful
        """
        if name not in self._skills:
            return

        skill = self._skills[name]
        skill.usage_count += 1
        if success:
            skill.success_count += 1

        # Update index
        if name in self._index.get("skills", {}):
            self._index["skills"][name]["usage_count"] = skill.usage_count
            self._index["skills"][name]["success_count"] = skill.success_count
            self._save_index()

    def get_skill_listing(self) -> str:
        """Get a formatted listing of available skills.

        Returns:
            Human-readable skill listing
        """
        if not self._skills:
            return "No skills available."

        lines = ["# Available Skills\n"]
        for name, skill in sorted(self._skills.items()):
            sig = f" ({skill.signature})" if skill.signature else ""
            lines.append(f"- {name}{sig}: {skill.description}")

        return "\n".join(lines)

    def delete_skill(self, name: str) -> bool:
        """Delete a skill from the registry.

        Args:
            name: Skill name to delete

        Returns:
            True if deleted, False if not found
        """
        if name not in self._skills:
            return False

        # Remove file
        skill_file = self.skills_dir / f"{name}.py"
        try:
            if skill_file.exists():
                skill_file.unlink()
        except IOError as e:
            logger.error(f"Failed to delete skill file: {e}")

        # Update index
        if name in self._index.get("skills", {}):
            del self._index["skills"][name]
            self._save_index()

        # Remove from memory
        del self._skills[name]

        logger.info(f"Deleted skill: {name}")
        return True
