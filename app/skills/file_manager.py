"""Skill File Manager - manages skill files on disk"""
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.models.skill import Skill, SkillSource
from app.skills.templates import SKILL_TEMPLATES
from app.config import settings

logger = logging.getLogger(__name__)


class SkillFileManager:
    """
    Manages skill files on the filesystem:
    - Creates skill directories from templates
    - Reads/writes skill files
    - Deletes skills
    - Syncs between database and filesystem
    """

    def __init__(self, base_dir: Optional[str] = None):
        """
        Initialize SkillFileManager

        Args:
            base_dir: Base directory for skills (defaults to settings.SKILLS_BASE_DIR)
        """
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            self.base_dir = Path(__file__).parent.parent.parent / settings.SKILLS_BASE_DIR

        self.user_dir = self.base_dir / "user"
        self.builtin_dir = self.base_dir / "builtin"
        self.cached_dir = self.base_dir / "cached"

        # Ensure directories exist
        for dir_path in [self.base_dir, self.user_dir, self.builtin_dir, self.cached_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

    def get_skill_dir(self, skill_name: str, source: SkillSource = SkillSource.USER) -> Path:
        """
        Get the directory for a skill

        Args:
            skill_name: Name of the skill
            source: Source of the skill

        Returns:
            Path to the skill directory
        """
        if source == SkillSource.BUILTIN:
            return self.builtin_dir / skill_name
        elif source == SkillSource.GITHUB:
            return self.cached_dir / skill_name
        else:
            return self.user_dir / skill_name

    def get_file_list(self, skill_name: str, source: SkillSource = SkillSource.USER) -> List[Dict]:
        """
        Get list of files in a skill directory

        Args:
            skill_name: Name of the skill
            source: Source of the skill

        Returns:
            List of file info dicts
        """
        skill_dir = self.get_skill_dir(skill_name, source)
        if not skill_dir.exists():
            return []

        files = []
        for item in skill_dir.iterdir():
            if item.is_file():
                files.append({
                    "path": str(item.relative_to(skill_dir)),
                    "name": item.name,
                    "type": self._get_file_type(item.name),
                    "size": item.stat().st_size,
                    "last_modified": datetime.fromtimestamp(item.stat().st_mtime),
                })
        return files

    def _get_file_type(self, filename: str) -> str:
        """Get file type from filename extension"""
        ext = Path(filename).suffix.lower()
        type_map = {
            ".md": "markdown",
            ".py": "python",
            ".txt": "text",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".toml": "toml",
        }
        return type_map.get(ext, "other")

    def read_file(self, skill_name: str, file_path: str, source: SkillSource = SkillSource.USER) -> Optional[str]:
        """
        Read a file from a skill directory

        Args:
            skill_name: Name of the skill
            file_path: Path to the file (relative to skill dir)
            source: Source of the skill

        Returns:
            File content as string, or None if not found
        """
        skill_dir = self.get_skill_dir(skill_name, source)
        full_path = skill_dir / file_path

        if not full_path.exists():
            return None

        try:
            return full_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read file {file_path}: {e}")
            return None

    def write_file(self, skill_name: str, file_path: str, content: str, source: SkillSource = SkillSource.USER) -> bool:
        """
        Write a file to a skill directory

        Args:
            skill_name: Name of the skill
            file_path: Path to the file (relative to skill dir)
            content: Content to write
            source: Source of the skill

        Returns:
            True if successful
        """
        skill_dir = self.get_skill_dir(skill_name, source)
        skill_dir.mkdir(parents=True, exist_ok=True)

        full_path = skill_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # PowerShell scripts need UTF-8 BOM for Windows PowerShell 5.1 compatibility
            if full_path.suffix in ('.ps1',) and os.name == "nt":
                with open(full_path, "wb") as f:
                    f.write(b"\xef\xbb\xbf")  # UTF-8 BOM
                    f.write(content.encode("utf-8"))
            else:
                full_path.write_text(content, encoding="utf-8")
            logger.info(f"Written file {file_path} to skill {skill_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to write file {file_path}: {e}")
            return False

    def delete_file(self, skill_name: str, file_path: str, source: SkillSource = SkillSource.USER) -> bool:
        """
        Delete a file from a skill directory

        Args:
            skill_name: Name of the skill
            file_path: Path to the file (relative to skill dir)
            source: Source of the skill

        Returns:
            True if successful
        """
        skill_dir = self.get_skill_dir(skill_name, source)
        full_path = skill_dir / file_path

        if not full_path.exists():
            return False

        try:
            full_path.unlink()
            logger.info(f"Deleted file {file_path} from skill {skill_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file {file_path}: {e}")
            return False

    def create_skill_from_template(
        self,
        skill_name: str,
        template_name: str = "basic",
        description: str = "",
        author: str = "",
        tags: Optional[List[str]] = None,
    ) -> Path:
        """
        Create a new skill from a template

        Args:
            skill_name: Name of the new skill
            template_name: Name of the template to use
            description: Description of the skill
            author: Author of the skill
            tags: Tags for the skill

        Returns:
            Path to the created skill directory
        """
        template = SKILL_TEMPLATES.get(template_name)
        if not template:
            raise ValueError(f"Template {template_name} not found")

        skill_dir = self.get_skill_dir(skill_name, SkillSource.USER)
        if skill_dir.exists():
            raise ValueError(f"Skill {skill_name} already exists")

        skill_dir.mkdir(parents=True, exist_ok=True)

        # Create files from template
        for filename, template_content in template["files"].items():
            # Replace placeholders in content
            content = template_content
            content = content.replace("{{name}}", skill_name)
            content = content.replace("{{description}}", description or skill_name)
            content = content.replace("{{author}}", author or "anonymous")

            # Handle tags replacement
            if tags:
                tags_str = ", ".join(f'"{t}"' for t in tags)
            else:
                tags_str = '"custom"'
            content = content.replace("{{tags}}", tags_str)

            file_path = skill_dir / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        logger.info(f"Created skill {skill_name} from template {template_name}")
        return skill_dir

    def delete_skill(self, skill_name: str, source: SkillSource = SkillSource.USER) -> bool:
        """
        Delete an entire skill directory

        Args:
            skill_name: Name of the skill (or folder name)
            source: Source of the skill

        Returns:
            True if successful
        """
        skill_dir = self.get_skill_dir(skill_name, source)
        return self._delete_skill_dir(skill_dir, skill_name)

    def delete_skill_by_path(self, dir_path: str) -> bool:
        """
        Delete a skill directory by its full path

        Args:
            dir_path: Full path to the skill directory

        Returns:
            True if successful
        """
        if not dir_path:
            return False
        skill_dir = Path(dir_path)
        return self._delete_skill_dir(skill_dir, str(skill_dir))

    def _delete_skill_dir(self, skill_dir: Path, log_name: str) -> bool:
        """Internal method to delete a skill directory"""
        if not skill_dir.exists():
            return False

        try:
            shutil.rmtree(skill_dir)
            logger.info(f"Deleted skill directory: {log_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete skill directory {log_name}: {e}")
            return False

    def sync_skill_to_fs(self, skill: Skill) -> bool:
        """
        Sync a skill from database to filesystem

        Args:
            skill: Skill to sync

        Returns:
            True if successful
        """
        if not skill.dir_path and not skill.skill_content:
            return False

        # Determine target directory
        if skill.dir_path:
            skill_dir = Path(skill.dir_path)
        else:
            skill_dir = self.get_skill_dir(skill.name, skill.source)

        skill_dir.mkdir(parents=True, exist_ok=True)

        # Write skill.md
        skill_md_path = skill_dir / "skill.md"
        if skill.skill_content:
            skill_md_path.write_text(skill.skill_content, encoding="utf-8")

        # If we have a dir_path in DB, check if there are other files we should preserve
        # (For now, we just ensure skill.md exists)

        return True


# Global instance
_file_manager: Optional[SkillFileManager] = None


def get_skill_file_manager() -> SkillFileManager:
    """Get or create the global SkillFileManager"""
    global _file_manager
    if _file_manager is None:
        _file_manager = SkillFileManager()
    return _file_manager
