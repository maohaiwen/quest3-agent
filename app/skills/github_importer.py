"""GitHub Skill Importer - implements Git clone + cache management"""
import asyncio
import logging
import os
import re
import shutil
import subprocess
import zipfile
from datetime import datetime
from app.utils.timezone import beijing_now
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from app.models.skill import Skill, SkillSource
from app.skills.loader import SkillLoader

logger = logging.getLogger(__name__)


class GitHubRepoRef:
    """Parsed GitHub repository reference"""

    def __init__(
        self,
        owner: str,
        repo: str,
        ref: Optional[str] = None,
        subdir: Optional[str] = None,
    ):
        self.owner = owner
        self.repo = repo
        self.ref = ref or "HEAD"
        self.subdir = subdir

    @classmethod
    def parse(cls, url_or_path: str) -> "GitHubRepoRef":
        """
        Parse GitHub URL or path reference

        Supported formats:
        - github.com/owner/repo
        - github.com/owner/repo#tag
        - github.com/owner/repo/tree/main/path/to/skills
        - https://github.com/owner/repo.git
        """
        # Remove protocol if present
        url_or_path = url_or_path.replace("https://", "").replace("http://", "")
        url_or_path = url_or_path.replace(".git", "")

        # Split into parts
        parts = url_or_path.strip("/").split("/")

        owner = None
        repo = None
        ref = None
        subdir = None

        if len(parts) >= 2:
            if parts[0] == "github.com":
                parts = parts[1:]

            owner = parts[0]
            repo = parts[1]

            # Check for #ref suffix
            if "#" in repo:
                repo, ref = repo.split("#", 1)

            # Check for tree/ or blob/ paths
            if len(parts) > 2 and parts[2] in ("tree", "blob"):
                ref = parts[3] if len(parts) > 3 else None
                subdir = "/".join(parts[4:]) if len(parts) > 4 else None

        if not owner or not repo:
            raise ValueError(f"Invalid GitHub reference: {url_or_path}")

        return cls(owner=owner, repo=repo, ref=ref, subdir=subdir)

    def get_cache_key(self) -> str:
        """Get unique cache key for this reference"""
        key = f"{self.owner}_{self.repo}"
        if self.ref and self.ref != "HEAD":
            key += f"_{self.ref}"
        if self.subdir:
            key += f"_{self.subdir.replace('/', '_')}"
        return key

    def get_clone_url(self) -> str:
        """Get HTTPS clone URL"""
        return f"https://github.com/{self.owner}/{self.repo}.git"

    def get_zip_url(self) -> str:
        """Get zip archive download URL"""
        # Try to use the provided ref, or default to main if not specified
        if self.ref and self.ref != "HEAD":
            # Check if it looks like a commit hash (40 chars) or a branch/tag
            if len(self.ref) == 40 and all(c in '0123456789abcdefABCDEF' for c in self.ref):
                return f"https://github.com/{self.owner}/{self.repo}/archive/{self.ref}.zip"
            return f"https://github.com/{self.owner}/{self.repo}/archive/refs/heads/{self.ref}.zip"
        # Try main first, then master - will be handled by fallback logic
        return f"https://github.com/{self.owner}/{self.repo}/archive/refs/heads/main.zip"

    def __str__(self) -> str:
        path = f"github.com/{self.owner}/{self.repo}"
        if self.ref and self.ref != "HEAD":
            path += f"#{self.ref}"
        if self.subdir:
            path += f"/tree/{self.ref or 'HEAD'}/{self.subdir}"
        return path


class GitHubSkillImporter:
    """
    Imports skills from GitHub repositories using Git clone + cache
    """

    def __init__(self, cache_dir: Optional[str] = None):
        """
        Initialize GitHub Importer

        Args:
            cache_dir: Directory to cache cloned repositories
        """
        from app.config import settings
        base_dir = Path(__file__).parent.parent.parent
        self.cache_dir = Path(cache_dir) if cache_dir else (base_dir / settings.SKILLS_CACHED_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.skill_loader = SkillLoader()

    async def import_repo(
        self,
        repo_ref: str,
        auto_enable: bool = True,
        force_refresh: bool = False,
    ) -> Tuple[List[Skill], str]:
        """
        Import skills from a GitHub repository

        Args:
            repo_ref: GitHub repository reference (URL or path)
            auto_enable: Whether to auto-enable imported skills
            force_refresh: Force re-clone even if cached

        Returns:
            Tuple of (list of imported Skills, cache path)
        """
        ref = GitHubRepoRef.parse(repo_ref)
        cache_key = ref.get_cache_key()
        repo_cache_dir = self.cache_dir / cache_key

        logger.info(f"Importing from {ref}")

        # Clone or update repository
        if force_refresh and repo_cache_dir.exists():
            logger.info(f"Force refreshing: removing existing cache {repo_cache_dir}")
            try:
                shutil.rmtree(repo_cache_dir)
            except Exception as e:
                logger.warning(f"Could not remove cache dir: {e}")

        if not repo_cache_dir.exists():
            # Try git clone first
            try:
                await self._clone_repo(ref, repo_cache_dir)
            except Exception as e:
                logger.warning(f"Git clone failed: {e}, trying zip download...")
                # Fallback to zip download
                try:
                    await self._download_zip(ref, repo_cache_dir)
                except Exception as e2:
                    raise RuntimeError(
                        f"Failed to import from GitHub: {str(e)}; {str(e2)}"
                    )
        else:
            logger.info(f"Using cached repository: {repo_cache_dir}")

        # Find and load skills
        skill_dir = repo_cache_dir
        if ref.subdir:
            skill_dir = repo_cache_dir / ref.subdir

        skills = await self._load_skills_from_dir(skill_dir, ref, auto_enable)

        logger.info(f"Imported {len(skills)} skills from {ref}")
        return skills, str(repo_cache_dir)

    def _find_git(self) -> str:
        """Find git executable, especially on Windows"""
        # Common Windows Git paths
        common_paths = [
            r"C:\Program Files\Git\bin\git.exe",
            r"C:\Program Files (x86)\Git\bin\git.exe",
            r"C:\Program Files\Git\cmd\git.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Git\bin\git.exe"),
            os.path.expanduser(r"~\AppData\Local\Programs\Git\cmd\git.exe"),
        ]

        # Check if git is in PATH first
        git_path = shutil.which("git")
        if git_path:
            return git_path

        # Check common Windows paths
        for path in common_paths:
            if os.path.exists(path):
                return path

        raise RuntimeError(
            "Git command not found. Please install Git from https://git-scm.com/ "
            "and make sure it's in PATH or installed in a default location."
        )

    async def _clone_repo(self, ref: GitHubRepoRef, target_dir: Path) -> None:
        """Clone repository to target directory"""
        import subprocess

        git_exe = self._find_git()
        logger.info(f"Cloning {ref.get_clone_url()} to {target_dir} using {git_exe}")

        # Build git clone command
        cmd = [git_exe, "clone", "--depth", "1"]
        if ref.ref and ref.ref != "HEAD":
            cmd.extend(["--branch", ref.ref])
        cmd.extend([ref.get_clone_url(), str(target_dir)])

        try:
            # Run git clone in thread pool (compatible with Windows)
            def run_git():
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore'
                )
                return result.returncode, result.stdout, result.stderr

            returncode, stdout, stderr = await asyncio.to_thread(run_git)

            if returncode != 0:
                raise RuntimeError(f"Git clone failed: {stderr}")

            logger.info(f"Successfully cloned {ref}")

        except FileNotFoundError as e:
            raise RuntimeError(
                f"Git command not found at {git_exe}. Please install Git and make sure it's in PATH."
            )

    async def _download_zip(self, ref: GitHubRepoRef, target_dir: Path) -> None:
        """Download repository as zip archive"""
        zip_url = ref.get_zip_url()
        logger.info(f"Downloading {zip_url}")

        # Download zip
        zip_path = self.cache_dir / f"{ref.repo}.zip"

        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.get(zip_url, timeout=60.0)
                response.raise_for_status()

                with open(zip_path, "wb") as f:
                    f.write(response.content)

            logger.info(f"Downloaded zip to {zip_path}")

            # Extract zip
            temp_dir = self.cache_dir / f"{ref.repo}_temp"
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(temp_dir)

            # Find the extracted directory (it should be the only one)
            extracted_dirs = list(temp_dir.iterdir())
            if not extracted_dirs:
                raise RuntimeError("No directory found in zip")

            extracted_dir = extracted_dirs[0]

            # Move to final location
            shutil.move(str(extracted_dir), str(target_dir))

            # Cleanup
            shutil.rmtree(temp_dir)
            zip_path.unlink(missing_ok=True)

            logger.info(f"Successfully extracted {ref}")

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error downloading zip: {e}")
            if e.response.status_code == 404:
                # Try with "main" or "master"
                for branch in ["main", "master"]:
                    try:
                        ref.ref = branch
                        return await self._download_zip(ref, target_dir)
                    except Exception:
                        continue
            raise RuntimeError(f"Failed to download zip: {e}")
        except httpx.ConnectError as e:
            logger.error(f"Connection error downloading zip: {e}")
            raise RuntimeError(f"Failed to connect to GitHub: {e}. Please check your network connection.")
        except Exception as e:
            logger.error(f"Error processing zip: {e}", exc_info=True)
            raise RuntimeError(f"Failed to process zip: {e}")

    async def _load_skills_from_dir(
        self,
        dir_path: Path,
        ref: GitHubRepoRef,
        auto_enable: bool,
    ) -> List[Skill]:
        """Load all skills from a directory"""
        skills = []

        if not dir_path.exists():
            logger.warning(f"Directory not found: {dir_path}")
            return skills

        # Scan for skill directories
        for item in dir_path.iterdir():
            if item.is_dir():
                skill_md = item / "skill.md"
                if skill_md.exists():
                    try:
                        skill = self._load_single_skill(item, ref, auto_enable)
                        if skill:
                            skills.append(skill)
                    except Exception as e:
                        logger.error(f"Failed to load skill from {item}: {e}")

        # Also check if the directory itself is a skill
        skill_md = dir_path / "skill.md"
        if skill_md.exists():
            try:
                skill = self._load_single_skill(dir_path, ref, auto_enable)
                if skill:
                    skills.append(skill)
            except Exception as e:
                logger.error(f"Failed to load skill from {dir_path}: {e}")

        return skills

    def _load_single_skill(
        self,
        skill_dir: Path,
        ref: GitHubRepoRef,
        auto_enable: bool,
    ) -> Optional[Skill]:
        """Load a single skill from directory"""
        skill_md = skill_dir / "skill.md"
        if not skill_md.exists():
            return None

        # Use existing loader to parse
        content = skill_md.read_text(encoding="utf-8")
        metadata, _ = self.skill_loader._parse_frontmatter(content)

        # Check for entrypoint
        entrypoint = None
        main_py = skill_dir / "main.py"
        if main_py.exists():
            entrypoint = str(main_py.resolve())

        # Create skill with GitHub source
        skill = Skill(
            id=f"github_{ref.owner}_{ref.repo}_{metadata.name}",
            name=metadata.name,
            description=metadata.description,
            version=metadata.version,
            author=metadata.author,
            tags=metadata.tags + ["github", ref.owner],
            source=SkillSource.GITHUB,
            requirements=metadata.requirements,
            tools=metadata.tools,
            config_schema=metadata.config_schema,
            entrypoint=entrypoint,
            skill_content=content,
            dir_path=str(skill_dir.resolve()),
            enabled=auto_enable,
            created_at=datetime.fromtimestamp(skill_md.stat().st_ctime),
            updated_at=datetime.fromtimestamp(skill_md.stat().st_mtime),
        )

        # Store extra info in a safe place (using tags)
        skill.tags.extend([f"repo:{ref.owner}/{ref.repo}"])
        if ref.ref and ref.ref != "HEAD":
            skill.tags.append(f"ref:{ref.ref}")

        return skill

    def get_cached_repos(self) -> List[Dict]:
        """Get list of cached repositories"""
        cached = []
        if not self.cache_dir.exists():
            return cached

        for item in self.cache_dir.iterdir():
            if item.is_dir():
                git_dir = item / ".git"
                if git_dir.exists() or any((item / d).exists() for d in [".git", "skill.md"]):
                    cached.append({
                        "name": item.name,
                        "path": str(item),
                        "updated_at": datetime.fromtimestamp(item.stat().st_mtime),
                    })

        return cached

    def clear_cache(self, cache_key: Optional[str] = None) -> None:
        """
        Clear cached repositories

        Args:
            cache_key: Specific cache key to clear, or None to clear all
        """
        if cache_key:
            target_dir = self.cache_dir / cache_key
            if target_dir.exists():
                try:
                    shutil.rmtree(target_dir)
                    logger.info(f"Cleared cache: {target_dir}")
                except Exception as e:
                    logger.warning(f"Could not clear cache: {e}")
        else:
            if self.cache_dir.exists():
                for item in self.cache_dir.iterdir():
                    if item.is_dir():
                        try:
                            shutil.rmtree(item)
                        except Exception as e:
                            logger.warning(f"Could not remove {item}: {e}")
                logger.info("Cleared all cached repositories")


# Global importer instance
_importer: Optional[GitHubSkillImporter] = None


def get_github_importer() -> GitHubSkillImporter:
    """Get or create global GitHubSkillImporter instance"""
    global _importer
    if _importer is None:
        _importer = GitHubSkillImporter()
    return _importer
