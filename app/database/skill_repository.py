"""Skill repository for database operations"""
import json
import logging
from datetime import datetime
from app.utils.timezone import beijing_now
from typing import List, Optional, Dict, Any
from pathlib import Path

from app.database.connection import DatabaseConnection
from app.models.skill import (
    Skill,
    SkillCreate,
    SkillUpdate,
    SkillSource,
    SkillConfig,
    AgentSkillLink,
)
from app.skills.loader import SkillLoader

logger = logging.getLogger(__name__)


class SkillRepository:
    """Repository for skill database operations"""

    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.loader = SkillLoader()

    async def create_skill(self, skill_create: SkillCreate) -> Skill:
        """Create a new skill in database"""
        # Parse the skill content to get metadata
        skill = self.loader.load_skill_from_string(
            skill_create.name,
            skill_create.skill_content,
            skill_create.source,
        )

        skill_id = skill.id
        now = beijing_now().isoformat()

        sql = """
        INSERT INTO skills (
            id, name, description, version, author, tags, source,
            requirements, tools, config_schema, entrypoint, skill_content, dir_path,
            enabled, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        tags_json = json.dumps(skill.tags, ensure_ascii=False)
        requirements_json = json.dumps(skill.requirements, ensure_ascii=False)
        tools_json = json.dumps(skill.tools, ensure_ascii=False)
        config_schema_json = json.dumps(skill.config_schema.model_dump()) if skill.config_schema else None

        await self.db.execute(sql, (
            skill_id,
            skill.name,
            skill.description,
            skill.version,
            skill.author,
            tags_json,
            skill.source.value,
            requirements_json,
            tools_json,
            config_schema_json,
            skill.entrypoint,
            skill.skill_content,
            skill.dir_path,
            1 if skill.enabled else 0,
            now,
            now,
        ))
        await self.db.commit()

        return await self.get_skill_by_id(skill_id)

    async def get_skill_by_id(self, skill_id: str) -> Optional[Skill]:
        """Get a skill by ID"""
        sql = "SELECT * FROM skills WHERE id = ?"
        row = await self.db.fetch_one(sql, (skill_id,))
        return self._row_to_skill(row) if row else None

    async def get_skill_by_name(self, name: str) -> Optional[Skill]:
        """Get a skill by name"""
        sql = "SELECT * FROM skills WHERE name = ?"
        row = await self.db.fetch_one(sql, (name,))
        return self._row_to_skill(row) if row else None

    async def get_all_skills(self, include_disabled: bool = False) -> List[Skill]:
        """Get all skills"""
        if include_disabled:
            sql = "SELECT * FROM skills ORDER BY name"
            rows = await self.db.fetch_all(sql)
        else:
            sql = "SELECT * FROM skills WHERE enabled = 1 ORDER BY name"
            rows = await self.db.fetch_all(sql)
        return [self._row_to_skill(row) for row in rows]

    async def update_skill(self, skill_id: str, skill_update: SkillUpdate) -> Optional[Skill]:
        """Update a skill"""
        skill = await self.get_skill_by_id(skill_id)
        if not skill:
            return None

        updates = []
        params = []

        if skill_update.description is not None:
            updates.append("description = ?")
            params.append(skill_update.description)

        if skill_update.skill_content is not None:
            # Re-parse the content to get updated metadata
            parsed_skill = self.loader.load_skill_from_string(
                skill.name,
                skill_update.skill_content,
                skill.source,
            )
            updates.append("skill_content = ?")
            updates.append("description = ?")
            updates.append("version = ?")
            updates.append("author = ?")
            updates.append("tags = ?")
            updates.append("requirements = ?")
            updates.append("tools = ?")
            updates.append("config_schema = ?")
            params.extend([
                skill_update.skill_content,
                parsed_skill.description,
                parsed_skill.version,
                parsed_skill.author,
                json.dumps(parsed_skill.tags, ensure_ascii=False),
                json.dumps(parsed_skill.requirements, ensure_ascii=False),
                json.dumps(parsed_skill.tools, ensure_ascii=False),
                json.dumps(parsed_skill.config_schema.model_dump()) if parsed_skill.config_schema else None,
            ])

        if skill_update.enabled is not None:
            updates.append("enabled = ?")
            params.append(1 if skill_update.enabled else 0)

        if updates:
            updates.append("updated_at = ?")
            params.append(beijing_now().isoformat())
            params.append(skill_id)

            sql = f"UPDATE skills SET {', '.join(updates)} WHERE id = ?"
            await self.db.execute(sql, tuple(params))
            await self.db.commit()

        return await self.get_skill_by_id(skill_id)

    async def delete_skill(self, skill_id: str) -> bool:
        """Delete a skill"""
        # First delete all agent associations
        await self.db.execute("DELETE FROM agent_skills WHERE skill_id = ?", (skill_id,))
        # Then delete the skill
        result = await self.db.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
        await self.db.commit()
        return result.rowcount > 0 if hasattr(result, 'rowcount') else True

    # Agent-Skill association methods

    async def link_agent_skill(self, link: AgentSkillLink) -> None:
        """Link a skill to an agent"""
        now = beijing_now().isoformat()
        sql = """
        INSERT OR REPLACE INTO agent_skills (agent_id, skill_id, enabled, priority, created_at)
        VALUES (?, ?, ?, ?, ?)
        """
        await self.db.execute(sql, (
            link.agent_id,
            link.skill_id,
            1 if link.enabled else 0,
            link.priority,
            now,
        ))
        await self.db.commit()

    async def unlink_agent_skill(self, agent_id: str, skill_id: str) -> bool:
        """Unlink a skill from an agent"""
        result = await self.db.execute(
            "DELETE FROM agent_skills WHERE agent_id = ? AND skill_id = ?",
            (agent_id, skill_id)
        )
        await self.db.commit()
        return result.rowcount > 0 if hasattr(result, 'rowcount') else True

    async def get_agent_skills(self, agent_id: str) -> List[Skill]:
        """Get all skills linked to an agent"""
        sql = """
        SELECT s.* FROM skills s
        INNER JOIN agent_skills ag ON s.id = ag.skill_id
        WHERE ag.agent_id = ? AND ag.enabled = 1 AND s.enabled = 1
        ORDER BY ag.priority DESC
        """
        rows = await self.db.fetch_all(sql, (agent_id,))
        return [self._row_to_skill(row) for row in rows]

    async def get_agent_skill_links(self, agent_id: str) -> List[AgentSkillLink]:
        """Get agent-skill links"""
        sql = "SELECT * FROM agent_skills WHERE agent_id = ?"
        rows = await self.db.fetch_all(sql, (agent_id,))
        return [
            AgentSkillLink(
                agent_id=row["agent_id"],
                skill_id=row["skill_id"],
                enabled=bool(row["enabled"]),
                priority=row["priority"],
            )
            for row in rows
        ]

    async def sync_from_filesystem(self, skill_dirs: List[str]) -> int:
        """Sync skills from filesystem to database"""
        for dir_path in skill_dirs:
            self.loader.add_skill_dir(dir_path)

        skills = self.loader.scan_skills(reload=True)
        count = 0

        for skill in skills.values():
            # Check if skill already exists
            existing = await self.get_skill_by_name(skill.name)
            if not existing:
                # Create from Skill object
                skill_create = SkillCreate(
                    name=skill.name,
                    description=skill.description,
                    skill_content=skill.skill_content,
                    source=skill.source,
                )
                await self.create_skill(skill_create)
                count += 1

        logger.info(f"Synced {count} skills from filesystem")
        return count

    def _row_to_skill(self, row: Dict[str, Any]) -> Skill:
        """Convert a database row to a Skill object"""
        tags = json.loads(row["tags"]) if row.get("tags") else []
        tools = json.loads(row["tools"]) if row.get("tools") else []
        requirements = json.loads(row.get("requirements", "[]")) if row.get("requirements") else []

        config_schema = None
        if row.get("config_schema"):
            try:
                config_schema = SkillConfig(**json.loads(row["config_schema"]))
            except Exception:
                pass

        return Skill(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            version=row["version"] or "1.0.0",
            author=row.get("author"),
            tags=tags,
            source=SkillSource(row["source"]) if row.get("source") else SkillSource.USER,
            requirements=requirements,
            tools=tools,
            config_schema=config_schema,
            entrypoint=row.get("entrypoint"),
            skill_content=row["skill_content"],
            dir_path=row.get("dir_path"),
            enabled=bool(row["enabled"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
