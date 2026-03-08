"""
SkillsBench Task Loader

Loads tasks from the SkillsBench dataset (benchflow-ai/skillsbench) and
adapts them to the PTC-Bench task schema.

SkillsBench task structure:
    tasks/{task_id}/
        - task.toml         # Metadata (difficulty, category, timeouts)
        - instruction.md    # Task description for agent
        - environment/      # Setup files and data
        - solution/         # Reference solution
        - tests/            # Validation scripts
"""

import json
import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

import requests

from ..tasks.schema import Task

logger = logging.getLogger(__name__)


@dataclass
class SkillsBenchTask:
    """Raw SkillsBench task structure."""
    id: str
    metadata: Dict[str, Any]
    instruction: str
    environment_files: List[Dict[str, str]] = field(default_factory=list)
    test_script: Optional[str] = None
    verifier_script: Optional[str] = None
    solution_code: Optional[str] = None


class SkillsBenchLoader:
    """
    Loads SkillsBench tasks from GitHub repository or local clone.
    
    SkillsBench uses Harbor framework task format:
    - task.toml: version, metadata, verifier, agent, environment settings
    - instruction.md: The actual task prompt
    - environment/: Files to set up in container
    - tests/: test.sh and test_outputs.py for validation
    - solution/: Reference implementation
    """
    
    GITHUB_RAW_URL = "https://raw.githubusercontent.com/benchflow-ai/skillsbench/main"
    GITHUB_API_URL = "https://api.github.com/repos/benchflow-ai/skillsbench"
    
    def __init__(
        self,
        local_path: Optional[str] = None,
        use_github_api: bool = True,
        cache_dir: Optional[str] = None,
    ):
        """
        Initialize loader.
        
        Args:
            local_path: Path to local clone of skillsbench repo
            use_github_api: If True and local_path not provided, fetch from GitHub
            cache_dir: Directory to cache downloaded tasks
        """
        self.local_path = Path(local_path) if local_path else None
        self.use_github_api = use_github_api
        self.cache_dir = Path(cache_dir) if cache_dir else Path(__file__).parent / ".cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._task_list_cache: Optional[List[str]] = None
        
    def list_tasks(self, use_cache: bool = True) -> List[str]:
        """
        List all available SkillsBench task IDs.
        
        Returns:
            List of task IDs (directory names from tasks/ folder)
        """
        if use_cache and self._task_list_cache is not None:
            return self._task_list_cache
            
        if self.local_path:
            # Load from local clone
            tasks_dir = self.local_path / "tasks"
            if tasks_dir.exists():
                task_ids = [d.name for d in tasks_dir.iterdir() if d.is_dir()]
            else:
                task_ids = []
        else:
            # Fetch from GitHub API
            task_ids = self._fetch_task_list_from_github()
            
        self._task_list_cache = sorted(task_ids)
        return self._task_list_cache
    
    def _fetch_task_list_from_github(self) -> List[str]:
        """Fetch list of tasks from GitHub API."""
        try:
            url = f"{self.GITHUB_API_URL}/contents/tasks?ref=main"
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            items = response.json()
            task_ids = [item["name"] for item in items if item["type"] == "dir"]
            return task_ids
        except Exception as e:
            logger.warning(f"Failed to fetch task list from GitHub: {e}")
            return []
    
    def _fetch_file_from_github(self, path: str) -> Optional[str]:
        """Fetch a file from GitHub raw content."""
        try:
            url = f"{self.GITHUB_RAW_URL}/{path}"
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                return response.text
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch {path}: {e}")
            return None
    
    def load_task(self, task_id: str) -> SkillsBenchTask:
        """
        Load a single SkillsBench task.
        
        Args:
            task_id: The task directory name (e.g., "citation-check")
            
        Returns:
            SkillsBenchTask with all task data
        """
        task_path = f"tasks/{task_id}"
        
        # Load task.toml metadata
        metadata = self._load_task_metadata(task_path)
        
        # Load instruction
        instruction = self._load_instruction(task_path)
        
        # Load environment files
        env_files = self._load_environment_files(task_path)
        
        # Load test scripts
        test_script = self._load_test_script(task_path)
        verifier_script = self._load_verifier_script(task_path)
        
        # Load solution
        solution = self._load_solution(task_path)
        
        return SkillsBenchTask(
            id=task_id,
            metadata=metadata,
            instruction=instruction,
            environment_files=env_files,
            test_script=test_script,
            verifier_script=verifier_script,
            solution_code=solution,
        )
    
    def _load_task_metadata(self, task_path: str) -> Dict[str, Any]:
        """Load task.toml metadata."""
        toml_content = self._get_file(f"{task_path}/task.toml")
        if toml_content:
            try:
                return tomllib.loads(toml_content)
            except Exception as e:
                logger.warning(f"Failed to parse TOML for {task_path}: {e}")
        return {}
    
    def _load_instruction(self, task_path: str) -> str:
        """Load instruction.md content."""
        content = self._get_file(f"{task_path}/instruction.md")
        return content or ""
    
    def _load_environment_files(self, task_path: str) -> List[Dict[str, str]]:
        """Load environment file references."""
        env_files = []
        env_path = f"{task_path}/environment"
        
        if self.local_path:
            local_env = self.local_path / env_path
            if local_env.exists():
                for file_path in local_env.rglob("*"):
                    if file_path.is_file():
                        rel_path = file_path.relative_to(local_env)
                        env_files.append({
                            "path": str(rel_path),
                            "local_source": str(file_path),
                        })
        else:
            # For GitHub, we'd need to fetch directory listing
            # This is simplified - in practice, we'd parse the environment structure
            pass
            
        return env_files
    
    def _load_test_script(self, task_path: str) -> Optional[str]:
        """Load tests/test.sh script."""
        return self._get_file(f"{task_path}/tests/test.sh")
    
    def _load_verifier_script(self, task_path: str) -> Optional[str]:
        """Load tests/test_outputs.py verifier."""
        return self._get_file(f"{task_path}/tests/test_outputs.py")
    
    def _extract_expected_output(self, task_path: str, task_id: str) -> Optional[str]:
        """Extract expected output from test file or solution."""
        # Try to get from test file
        test_content = self._get_file(f"{task_path}/tests/test_outputs.py")
        if test_content:
            # Look for EXPECTED_* variables or similar patterns
            import re
            # Match patterns like EXPECTED_FAKE_CITATIONS = [...]
            match = re.search(r'EXPECTED_\w+\s*=\s*(\[[^\]]+\]|"[^"]+"|\{[^\}]+\})', test_content)
            if match:
                return match.group(1)
        
        # Try solution file
        solution = self._load_solution(task_path)
        if solution:
            # Last line of solution might be the expected output
            lines = solution.strip().split('\n')
            for line in reversed(lines):
                if 'print' in line or 'output' in line.lower():
                    # Extract string from print statement
                    match = re.search(r'["\']([^"\']+)["\']', line)
                    if match:
                        return match.group(1)
        
        return None
    
    def _load_solution(self, task_path: str) -> Optional[str]:
        """Load reference solution from solution/ directory."""
        # Try common solution file names
        for filename in ["solution.py", "solve.py", "main.py", "script.py"]:
            content = self._get_file(f"{task_path}/solution/{filename}")
            if content:
                return content
        return None
    
    def _get_file(self, relative_path: str) -> Optional[str]:
        """Get file content from local path or GitHub."""
        # Check cache first
        cache_file = self.cache_dir / relative_path.replace("/", "_")
        if cache_file.exists():
            return cache_file.read_text()
        
        content = None
        
        if self.local_path:
            local_file = self.local_path / relative_path
            if local_file.exists():
                content = local_file.read_text()
        
        if content is None and self.use_github_api:
            content = self._fetch_file_from_github(relative_path)
        
        # Cache if found
        if content:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(content)
            
        return content
    
    def to_ptc_task(self, sb_task: SkillsBenchTask) -> Task:
        """
        Convert SkillsBench task to PTC-Bench Task schema.
        
        This adapts the SkillsBench format to our benchmark runner's
        expected task structure.
        """
        metadata = sb_task.metadata
        task_meta = metadata.get("metadata", {})
        
        # Map difficulty
        difficulty = task_meta.get("difficulty", "medium")
        
        # Map category
        category = task_meta.get("category", "general")
        
        # Get timeout
        agent_config = metadata.get("agent", {})
        timeout = int(agent_config.get("timeout_sec", 300))
        
        # Build setup files from environment
        setup_files = []
        for env_file in sb_task.environment_files:
            if "local_source" in env_file:
                setup_files.append({
                    "path": env_file["path"],
                    "source": env_file["local_source"],
                })
        
        # Try to extract expected output for proper evaluation
        expected_output = self._extract_expected_output(f"tasks/{sb_task.id}", sb_task.id)
        
        # If we have expected output, use exact match; otherwise fall back to output_present
        validation_type = "exact" if expected_output else "output_present"
        
        return Task(
            id=sb_task.id.upper().replace("-", "_"),
            name=sb_task.id,
            description=task_meta.get("tags", [""])[0] if task_meta.get("tags") else "",
            difficulty=difficulty,
            category=category,
            prompt=sb_task.instruction,
            reference_code=sb_task.solution_code or "",
            expected_output=expected_output,
            validation_type=validation_type,
            custom_validator=None,
            timeout=timeout,
            setup_files=setup_files,
            supported_backends=["opensandbox", "subprocess"],
            tags=task_meta.get("tags", []),
        )
    
    def load_tasks(
        self,
        categories: Optional[List[str]] = None,
        difficulties: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[Task]:
        """
        Load and convert multiple SkillsBench tasks.
        
        Args:
            categories: Filter by category (e.g., ["research", "games"])
            difficulties: Filter by difficulty (e.g., ["easy", "medium"])
            limit: Maximum number of tasks to load
            
        Returns:
            List of PTC-Bench Task objects
        """
        task_ids = self.list_tasks()
        tasks = []
        
        for task_id in task_ids:
            try:
                sb_task = self.load_task(task_id)
                metadata = sb_task.metadata.get("metadata", {})
                
                # Apply filters
                if categories and metadata.get("category") not in categories:
                    continue
                if difficulties and metadata.get("difficulty") not in difficulties:
                    continue
                
                ptc_task = self.to_ptc_task(sb_task)
                tasks.append(ptc_task)
                
                if limit and len(tasks) >= limit:
                    break
                    
            except Exception as e:
                logger.warning(f"Failed to load task {task_id}: {e}")
                continue
        
        logger.info(f"Loaded {len(tasks)} SkillsBench tasks")
        return tasks
    
    def get_skill_context(self, task_id: str) -> Optional[str]:
        """
        Get the curated skill context for a task if available.
        
        SkillsBench includes curated skills in environment/skills/ directory.
        This loads the SKILL.md and any associated skill code.
        """
        task_path = f"tasks/{task_id}"
        
        # SkillsBench stores curated skills in environment/skills/
        if self.local_path:
            env_skills_path = self.local_path / task_path / "environment" / "skills"
            if env_skills_path.exists():
                # Find all skill directories
                skill_contents = []
                for skill_dir in env_skills_path.iterdir():
                    if skill_dir.is_dir():
                        skill_md = skill_dir / "SKILL.md"
                        if skill_md.exists():
                            content = skill_md.read_text()
                            skill_contents.append(f"## Skill: {skill_dir.name}\n{content}")
                        
                        # Also check for skill code
                        skill_py = skill_dir / "scripts" / f"{skill_dir.name}.py"
                        if skill_py.exists():
                            code = skill_py.read_text()
                            skill_contents.append(f"```python\n{code}\n```")
                
                if skill_contents:
                    return "\n\n".join(skill_contents)
        
        # Fallback: try old paths for compatibility
        skill_content = self._get_file(f"{task_path}/skills/skill.md")
        if skill_content:
            return skill_content
        
        skill_code = self._get_file(f"{task_path}/skills/skill.py")
        if skill_code:
            return skill_code
            
        return None
