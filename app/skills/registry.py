"""Skill Registry - manages all available skills and agent associations"""
import logging
from typing import Dict, List, Optional, Set
from pathlib import Path

from app.models.skill import (
    Skill,
    SkillSummary,
    SkillMetadata,
    SkillSource,
    AgentSkillLink,
)
from app.skills.loader import SkillLoader
from app.skills.github_importer import GitHubSkillImporter, get_github_importer

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    Central registry for skills:
    - Manages loaded skills
    - Handles agent-skill associations
    - Provides skill discovery
    """

    def __init__(self, skill_dirs: Optional[List[str]] = None):
        """Initialize SkillRegistry"""
        self.loader = SkillLoader(skill_dirs)
        self._skills: Dict[str, Skill] = {}
        self._agent_links: Dict[str, List[AgentSkillLink]] = {}  # agent_id -> links
        self._loaded = False
        self._github_importer: Optional[GitHubSkillImporter] = None

    def add_skill_dir(self, dir_path: str) -> None:
        """Add a directory to scan for skills"""
        self.loader.add_skill_dir(dir_path)

    def initialize(self) -> None:
        """Initialize the registry - scan and load skills"""
        logger.info("Initializing SkillRegistry...")
        self._skills = self.loader.scan_skills()
        self._loaded = True
        logger.info(f"Loaded {len(self._skills)} skills")

    def get_all_skills(self) -> Dict[str, Skill]:
        """Get all available skills"""
        if not self._loaded:
            self.initialize()
        return self._skills

    def get_all_summaries(self) -> Dict[str, SkillSummary]:
        """Get all skill summaries (token-efficient)"""
        return self.loader.get_all_summaries()

    def get_skill(self, skill_name: str) -> Optional[Skill]:
        """Get a skill by name (frontmatter name)"""
        if not self._loaded:
            self.initialize()
        return self._skills.get(skill_name)

    def get_skill_by_dir_name(self, dir_name: str) -> Optional[Skill]:
        """Get a skill by directory name"""
        if not self._loaded:
            self.initialize()

        # First try direct lookup (if dir_name == frontmatter name)
        skill = self._skills.get(dir_name)
        if skill:
            return skill

        # Search by dir_path
        for skill in self._skills.values():
            if skill.dir_path:
                # dir_path is the full path, extract the last directory name
                skill_dir_name = Path(skill.dir_path).name
                if skill_dir_name == dir_name:
                    return skill

        return None

    def get_skill_content(self, skill_name: str) -> Optional[str]:
        """Get full skill.md content for injection"""
        return self.loader.load_skill_content(skill_name)

    def add_skill(self, skill: Skill) -> None:
        """Add a skill to the registry"""
        self._skills[skill.name] = skill
        logger.info(f"Added skill: {skill.name}")

    def remove_skill(self, skill_name: str) -> bool:
        """Remove a skill from the registry"""
        if skill_name in self._skills:
            del self._skills[skill_name]
            # Also remove from all agent links
            for agent_id in self._agent_links:
                self._agent_links[agent_id] = [
                    link for link in self._agent_links[agent_id]
                    if link.skill_id != skill_name
                ]
            logger.info(f"Removed skill: {skill_name}")
            return True
        return False

    # Agent-Skill association methods

    def link_agent_skill(self, link: AgentSkillLink) -> None:
        """Link a skill to an agent"""
        if link.agent_id not in self._agent_links:
            self._agent_links[link.agent_id] = []

        # Remove existing link if present
        self._agent_links[link.agent_id] = [
            l for l in self._agent_links[link.agent_id]
            if l.skill_id != link.skill_id
        ]

        self._agent_links[link.agent_id].append(link)
        logger.info(f"Linked skill {link.skill_id} to agent {link.agent_id}")

    def unlink_agent_skill(self, agent_id: str, skill_id: str) -> bool:
        """Unlink a skill from an agent"""
        if agent_id in self._agent_links:
            original_len = len(self._agent_links[agent_id])
            self._agent_links[agent_id] = [
                link for link in self._agent_links[agent_id]
                if link.skill_id != skill_id
            ]
            return len(self._agent_links[agent_id]) < original_len
        return False

    def get_agent_skills(self, agent_id: str) -> List[Skill]:
        """Get all skills linked to an agent"""
        if not self._loaded:
            self.initialize()

        if agent_id not in self._agent_links:
            return []

        # Create skill lookup by ID
        skills_by_id = {skill.id: skill for skill in self._skills.values()}

        skills = []
        priority_map = {}
        for link in self._agent_links[agent_id]:
            if link.enabled and link.skill_id in skills_by_id:
                skill = skills_by_id[link.skill_id]
                skills.append(skill)
                priority_map[skill.id] = link.priority

        # Sort by priority
        skills.sort(key=lambda s: priority_map.get(s.id, 0), reverse=True)

        return skills

    def get_agent_skill_summaries(self, agent_id: str) -> List[SkillSummary]:
        """Get skill summaries for an agent (token-efficient)"""
        agent_skills = self.get_agent_skills(agent_id)
        return [
            SkillSummary(
                name=skill.name,
                description=skill.description,
                tags=skill.tags,
            )
            for skill in agent_skills
        ]

    def get_system_prompt_addition(self, agent_id: str) -> str:
        """
        Get the system prompt addition for an agent's skills (layer 1: startup)

        This is injected into the agent's system prompt to let it know
        what skills are available.
        """
        summaries = self.get_agent_skill_summaries(agent_id)
        if not summaries:
            return ""

        lines = ["\n【绑定技能】"]
        lines.append("你绑定了以下专业技能。当用户的问题涉及这些技能的领域时，你 MUST 先加载对应技能再执行，不要跳过技能自行回答。")
        for summary in summaries:
            desc = summary.description or "（无描述）"
            tags_str = f" [标签: {', '.join(summary.tags)}]" if summary.tags else ""
            lines.append(f"- **{summary.name}**: {desc}{tags_str}")

        lines.append("\n【技能使用流程 - 必须遵守】")
        lines.append("1. 判断用户问题是否涉及上述技能领域。如果是，MUST 先调用 load_skill 加载对应技能的完整说明书。")
        lines.append("2. 加载技能后，严格按照技能说明书中的工作方式、分析框架和步骤来执行任务。")
        lines.append("3. 优先使用技能声明的工具来获取数据（如行业数据工具、搜索工具等），不要仅凭自身知识回答。")
        lines.append("4. 如果技能有可执行脚本（has_entrypoint=true），MUST 调用 execute_skill 执行，将用户意图传入 input_data。")
        lines.append("5. 禁止跳过技能直接用自己的知识回答相关领域问题，必须先加载技能再执行。")
        return "\n".join(lines)

    def reload(self) -> None:
        """Reload all skills from disk"""
        logger.info("Reloading skills...")
        self._loaded = False
        self.initialize()

    def get_skills_by_tag(self, tag: str) -> List[Skill]:
        """Get all skills with a specific tag"""
        if not self._loaded:
            self.initialize()

        return [
            skill for skill in self._skills.values()
            if tag in skill.tags
        ]

    def search_skills(self, query: str) -> List[Skill]:
        """Search skills by name or description"""
        if not self._loaded:
            self.initialize()

        query_lower = query.lower()
        results = []

        for skill in self._skills.values():
            if (query_lower in skill.name.lower() or
                query_lower in skill.description.lower() or
                any(query_lower in tag.lower() for tag in skill.tags)):
                results.append(skill)

        return results

    async def import_from_github(
        self,
        repo_ref: str,
        auto_enable: bool = True,
        force_refresh: bool = False,
    ) -> List[Skill]:
        """
        Import skills from GitHub

        Args:
            repo_ref: GitHub repository reference
            auto_enable: Whether to auto-enable imported skills
            force_refresh: Force re-clone even if cached

        Returns:
            List of imported skills
        """
        if self._github_importer is None:
            self._github_importer = get_github_importer()

        skills, cache_path = await self._github_importer.import_repo(
            repo_ref,
            auto_enable=auto_enable,
            force_refresh=force_refresh,
        )

        # Add to loader and registry
        self.loader.add_github_skills(skills)

        for skill in skills:
            self._skills[skill.name] = skill

        logger.info(f"Imported {len(skills)} skills from GitHub: {repo_ref}")
        return skills

    def get_github_importer(self) -> GitHubSkillImporter:
        """Get the GitHub importer instance"""
        if self._github_importer is None:
            self._github_importer = get_github_importer()
        return self._github_importer


# Global registry instance
_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    """Get or create the global skill registry"""
    global _registry
    if _registry is None:
        # Set up default skill directories
        from app.config import settings
        base_dir = Path(__file__).parent.parent.parent
        skill_dirs = [
            str(base_dir / settings.SKILLS_BUILTIN_DIR),
            str(base_dir / settings.SKILLS_USER_DIR),
        ]
        _registry = SkillRegistry(skill_dirs)
    return _registry
