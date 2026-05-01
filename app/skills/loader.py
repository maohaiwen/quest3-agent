"""Skill Loader - implements the three-layer loading mechanism"""
import os
import re
import yaml
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime

from app.models.skill import (
    Skill,
    SkillSummary,
    SkillMetadata,
    SkillSource,
    SkillConfig,
)

logger = logging.getLogger(__name__)

FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


class SkillLoader:
    """
    Skill Loader implementing three-layer loading:

    1. Startup layer: Load only metadata (name + description)
    2. Trigger layer: Load full skill.md content when needed
    3. Execution layer: Execute scripts if needed
    """

    def __init__(self, skill_dirs: Optional[List[str]] = None, github_cache_dir: Optional[str] = None):
        """
        Initialize SkillLoader

        Args:
            skill_dirs: List of directories to scan for skills
            github_cache_dir: Directory for cached GitHub repos
        """
        self.skill_dirs = skill_dirs or []
        self._skills_cache: Dict[str, Skill] = {}
        self._summaries_cache: Dict[str, SkillSummary] = {}
        self._github_skills: Dict[str, Skill] = {}  # GitHub imported skills

    def add_skill_dir(self, dir_path: str) -> None:
        """Add a directory to scan for skills"""
        path = Path(dir_path)
        if path.exists() and path.is_dir():
            self.skill_dirs.append(str(path.resolve()))
            logger.info(f"Added skill directory: {path}")
        else:
            logger.warning(f"Skill directory not found: {path}")

    def scan_skills(self, reload: bool = False) -> Dict[str, Skill]:
        """
        Scan all skill directories and load skills

        Args:
            reload: Force reload even if cached

        Returns:
            Dictionary of skills by name
        """
        if not reload and self._skills_cache:
            return self._skills_cache

        skills = {}

        for skill_dir in self.skill_dirs:
            dir_path = Path(skill_dir)
            if not dir_path.exists():
                continue

            # Each subdirectory is a skill
            for item in dir_path.iterdir():
                if item.is_dir():
                    skill_md = item / "skill.md"
                    if skill_md.exists():
                        try:
                            skill = self._load_skill_from_dir(item, SkillSource.BUILTIN if "builtin" in str(skill_dir) else SkillSource.USER)
                            if skill:
                                skills[skill.name] = skill
                                logger.info(f"Loaded skill: {skill.name} from {item}")
                        except Exception as e:
                            logger.error(f"Failed to load skill from {item}: {e}")

        self._skills_cache = skills
        self._summaries_cache = {name: self._create_summary(skill) for name, skill in skills.items()}
        return skills

    def get_all_summaries(self) -> Dict[str, SkillSummary]:
        """
        Get all skill summaries (for layer 1: startup loading)

        Returns:
            Dictionary of skill summaries by name
        """
        if not self._summaries_cache:
            self.scan_skills()
        return self._summaries_cache

    def get_summary(self, skill_name: str) -> Optional[SkillSummary]:
        """Get a single skill summary"""
        summaries = self.get_all_summaries()
        return summaries.get(skill_name)

    def get_skill(self, skill_name: str) -> Optional[Skill]:
        """
        Get full skill content (for layer 2: trigger loading)

        Args:
            skill_name: Name of the skill

        Returns:
            Skill object or None
        """
        skills = self.scan_skills()
        return skills.get(skill_name)

    def load_skill_content(self, skill_name: str) -> Optional[str]:
        """
        Load full skill.md content (for injection into context)

        Args:
            skill_name: Name of the skill

        Returns:
            Full skill.md content or None
        """
        skill = self.get_skill(skill_name)
        return skill.skill_content if skill else None

    def _load_skill_from_dir(self, dir_path: Path, source: SkillSource) -> Optional[Skill]:
        """
        Load a skill from a directory

        Args:
            dir_path: Path to skill directory
            source: Source type

        Returns:
            Skill object or None
        """
        skill_md = dir_path / "skill.md"
        if not skill_md.exists():
            return None

        content = skill_md.read_text(encoding="utf-8")
        metadata, content_body = self._parse_frontmatter(content)

        # Check for entrypoint - support Python, Shell, and PowerShell scripts
        # Priority is platform-aware:
        #   Windows: main.py > main.ps1 > main.sh
        #   Others:  main.py > main.sh > main.ps1
        entrypoint = None
        is_windows = os.name == "nt"
        if is_windows:
            entrypoint_candidates = ["main.py", "main.ps1", "main.sh"]
        else:
            entrypoint_candidates = ["main.py", "main.sh", "main.ps1"]
        for entrypoint_name in entrypoint_candidates:
            entrypoint_path = dir_path / entrypoint_name
            if entrypoint_path.exists():
                entrypoint = str(entrypoint_path.resolve())
                break

        # Collect all skill files (excluding skill.md)
        skill_files = metadata.files  # from frontmatter
        if not skill_files:
            # Auto-detect from filesystem
            skill_files = []
            for item in dir_path.iterdir():
                if item.is_file() and item.name != "skill.md":
                    skill_files.append(item.name)

        # Use frontmatter entrypoint if specified, otherwise keep auto-detected one
        if metadata.entrypoint and not entrypoint:
            # Frontmatter specified an entrypoint but file doesn't exist on disk yet
            ep_path = dir_path / metadata.entrypoint
            if ep_path.exists():
                entrypoint = str(ep_path.resolve())

        return Skill(
            id=f"{source.value}_{metadata.name}",
            name=metadata.name,
            description=metadata.description,
            version=metadata.version,
            author=metadata.author,
            tags=metadata.tags,
            source=source,
            requirements=metadata.requirements,
            tools=metadata.tools,
            config_schema=metadata.config_schema,
            entrypoint=entrypoint,
            files=skill_files,
            skill_content=content,
            dir_path=str(dir_path.resolve()),
            created_at=datetime.fromtimestamp(skill_md.stat().st_ctime),
            updated_at=datetime.fromtimestamp(skill_md.stat().st_mtime),
        )

    def _parse_frontmatter(self, content: str) -> Tuple[SkillMetadata, str]:
        """
        Parse YAML frontmatter from skill.md

        Args:
            content: Full skill.md content

        Returns:
            Tuple of (SkillMetadata, content_without_frontmatter)
        """
        match = FRONTMATTER_PATTERN.match(content)

        if match:
            frontmatter_str = match.group(1)
            content_body = content[match.end():]

            try:
                frontmatter = yaml.safe_load(frontmatter_str) or {}
            except yaml.YAMLError as e:
                logger.warning(f"Failed to parse frontmatter: {e}, using defaults")
                frontmatter = {}
        else:
            frontmatter = {}
            content_body = content

        # Parse config schema if present
        config_schema = None
        if "config_schema" in frontmatter:
            try:
                config_schema = SkillConfig(**frontmatter["config_schema"])
            except Exception as e:
                logger.warning(f"Failed to parse config_schema: {e}")

        # Sanitize tools: must be List[str], but LLM sometimes writes dicts
        raw_tools = frontmatter.get("tools", [])
        tools = []
        for item in raw_tools:
            if isinstance(item, str):
                tools.append(item)
            elif isinstance(item, dict):
                # LLM wrote a tool as a dict — extract the type or name
                tools.append(item.get("type", item.get("name", str(item))))

        # Sanitize tags: must be List[str]
        raw_tags = frontmatter.get("tags", [])
        tags = [str(t) for t in raw_tags]

        # Sanitize requirements: must be List[str]
        raw_reqs = frontmatter.get("requirements", [])
        requirements = [str(r) for r in raw_reqs]

        # Sanitize files: must be List[str]
        raw_files = frontmatter.get("files", [])
        files = [str(f) for f in raw_files]

        metadata = SkillMetadata(
            name=frontmatter.get("name", "unnamed_skill"),
            version=str(frontmatter.get("version", "1.0.0")),
            description=frontmatter.get("description", ""),
            author=frontmatter.get("author"),
            tags=tags,
            requirements=requirements,
            tools=tools,
            config_schema=config_schema,
            entrypoint=frontmatter.get("entrypoint"),
            files=files,
        )

        return metadata, content_body

    def _create_summary(self, skill: Skill) -> SkillSummary:
        """Create a summary from a skill"""
        return SkillSummary(
            name=skill.name,
            description=skill.description,
            tags=skill.tags,
        )

    def add_github_skills(self, skills: List[Skill]) -> None:
        """
        Add skills imported from GitHub

        Args:
            skills: List of Skill objects from GitHub
        """
        for skill in skills:
            # Override if exists
            self._github_skills[skill.name] = skill
            self._skills_cache[skill.name] = skill
            self._summaries_cache[skill.name] = self._create_summary(skill)
            logger.info(f"Added GitHub skill: {skill.name}")

    def load_skill_from_string(self, name: str, content: str, source: SkillSource = SkillSource.USER) -> Skill:
        """
        Load a skill from a string (for API-based creation)

        Args:
            name: Skill name
            content: Full skill.md content
            source: Source type

        Returns:
            Skill object
        """
        metadata, _ = self._parse_frontmatter(content)

        return Skill(
            id=f"{source.value}_{name}",
            name=name,
            description=metadata.description,
            version=metadata.version,
            author=metadata.author,
            tags=metadata.tags,
            source=source,
            requirements=metadata.requirements,
            tools=metadata.tools,
            config_schema=metadata.config_schema,
            entrypoint=metadata.entrypoint,
            skill_content=content,
            dir_path=None,
        )
