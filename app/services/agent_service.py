"""Agent service for managing intelligent assistant configurations"""
import asyncio
import logging
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.models.agent import AgentCreate, AgentUpdate, AgentResponse, AgentType
from app.database.connection import DatabaseConnection
from app.config import settings

logger = logging.getLogger(__name__)


class AgentService:
    """Service for managing agent configurations"""

    async def _sync_agent_skills_to_registry(self, agent_id: str, skill_names: List[str]):
        """Sync agent-skill links from database to memory registry"""
        try:
            from app.skills.registry import get_skill_registry
            from app.models.skill import AgentSkillLink

            registry = get_skill_registry()

            # Ensure registry is initialized
            if not registry._loaded:
                registry.initialize()

            # Clear existing links for this agent
            current_skills = registry.get_agent_skills(agent_id)
            for skill in current_skills:
                registry.unlink_agent_skill(agent_id, skill.id)

            # Add new links using skill names to match registry skills
            all_registry_skills = registry.get_all_skills()

            for skill_name in skill_names:
                for skill in all_registry_skills.values():
                    if skill.name == skill_name:
                        link = AgentSkillLink(
                            agent_id=agent_id,
                            skill_id=skill.id,
                            enabled=True,
                            priority=0
                        )
                        registry.link_agent_skill(link)
                        logger.info(f"Linked agent {agent_id} to skill {skill_name} (registry id: {skill.id})")
                        break
                else:
                    logger.warning(f"Skill {skill_name} not found in registry for agent {agent_id}")

        except Exception as e:
            logger.warning(f"Failed to sync agent skills to registry: {e}", exc_info=True)

    async def create(self, agent_data: AgentCreate) -> AgentResponse:
        """Create a new agent"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()

        try:
            agent_id = str(uuid.uuid4())
            now = datetime.utcnow()

            await db.execute("""
            INSERT INTO agents (id, name, description, type, execution_mode, system_prompt, model,
                              temperature, max_tokens, enabled, priority, thinking_effort, max_react_steps,
                              enable_long_term_memory, created_at, updated_at, usage_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                agent_id,
                agent_data.name,
                agent_data.description,
                agent_data.type.value if isinstance(agent_data.type, AgentType) else agent_data.type,
                agent_data.execution_mode or "plan",
                agent_data.system_prompt,
                agent_data.model,
                agent_data.temperature,
                agent_data.max_tokens,
                1 if agent_data.enabled else 0,
                agent_data.priority,
                getattr(agent_data, "thinking_effort", "medium"),
                getattr(agent_data, "max_react_steps", 15),
                1 if getattr(agent_data, "enable_long_term_memory", False) else 0,
                now.isoformat(),
                now.isoformat(),
                0
            ))

            for server_id in agent_data.mcp_servers:
                await db.execute("""
                INSERT INTO agent_mcp_servers (id, agent_id, server_id, enabled)
                VALUES (?, ?, ?, ?)
                """, (str(uuid.uuid4()), agent_id, server_id, 1))

            for tool_config in agent_data.tools:
                if isinstance(tool_config, str):
                    tool_name = tool_config
                    permission = "optional"
                    description = ""
                else:
                    tool_name = tool_config.get("tool_name", "")
                    permission = tool_config.get("permission", "optional")
                    description = tool_config.get("description", "")

                if tool_name:
                    await db.execute("""
                    INSERT INTO agent_tools (id, agent_id, tool_name, permission, description)
                    VALUES (?, ?, ?, ?, ?)
                    """, (str(uuid.uuid4()), agent_id, tool_name, permission, description))

            if hasattr(agent_data, "skills") and agent_data.skills:
                from app.database.skill_repository import SkillRepository
                from app.models.skill import AgentSkillLink

                skill_repo = SkillRepository(db)
                for skill_name in agent_data.skills:
                    skill = await skill_repo.get_skill_by_name(skill_name)
                    if skill:
                        link = AgentSkillLink(
                            agent_id=agent_id,
                            skill_id=skill.id,
                            enabled=True,
                            priority=0
                        )
                        await skill_repo.link_agent_skill(link)

            await db.commit()

        except Exception:
            await db.rollback()
            raise
        finally:
            await db.disconnect()

        # Post-commit: sync to registry and agent_registry
        agent = await self.get(agent_id)
        if agent:
            await self._sync_agent_skills_to_registry(agent_id, agent.skills)
            if agent.enabled:
                from app.services.agent_registry import agent_registry
                await agent_registry.register_existing_agent(agent)

        return agent

    async def get(self, agent_id: str) -> Optional[AgentResponse]:
        """Get agent by ID"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()

        try:
            agent_data = await db.fetch_one(
                "SELECT * FROM agents WHERE id = ?",
                (agent_id,)
            )

            if not agent_data:
                return None

            mcp_servers = await db.fetch_all(
                "SELECT server_id, enabled FROM agent_mcp_servers WHERE agent_id = ? AND enabled = 1",
                (agent_id,)
            )

            tools = await db.fetch_all(
                "SELECT tool_name, permission, description FROM agent_tools WHERE agent_id = ?",
                (agent_id,)
            )

            from app.database.skill_repository import SkillRepository
            skill_repo = SkillRepository(db)
            skills = await skill_repo.get_agent_skills(agent_id)
            skill_names = [skill.name for skill in skills]

            agent = AgentResponse(
                id=agent_data["id"],
                name=agent_data["name"],
                description=agent_data.get("description", ""),
                type=AgentType(agent_data.get("type", "custom")),
                execution_mode=agent_data.get("execution_mode", "plan"),
                system_prompt=agent_data.get("system_prompt", ""),
                model=agent_data.get("model"),
                temperature=agent_data.get("temperature"),
                max_tokens=agent_data.get("max_tokens"),
                enabled=bool(agent_data.get("enabled", 1)),
                priority=agent_data.get("priority", 0),
                created_at=datetime.fromisoformat(agent_data["created_at"]) if agent_data.get("created_at") else datetime.utcnow(),
                updated_at=datetime.fromisoformat(agent_data["updated_at"]) if agent_data.get("updated_at") else datetime.utcnow(),
                usage_count=agent_data.get("usage_count", 0),
                mcp_servers=[{"server_id": s["server_id"], "enabled": bool(s["enabled"])} for s in mcp_servers],
                tools=[t["tool_name"] for t in tools],
                skills=skill_names,
                thinking_effort=agent_data.get("thinking_effort", "medium"),
                max_react_steps=agent_data.get("max_react_steps", 15),
                enable_long_term_memory=bool(agent_data.get("enable_long_term_memory", 0))
            )

            # Sync to registry
            await self._sync_agent_skills_to_registry(agent_id, skill_names)

            return agent

        finally:
            await db.disconnect()

    async def list(self, enabled_only: bool = False) -> List[AgentResponse]:
        """List all agents (optimized - single query for agents, batched for related data)"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()

        try:
            if enabled_only:
                agents = await db.fetch_all("SELECT * FROM agents WHERE enabled = 1 ORDER BY priority DESC, created_at DESC")
            else:
                agents = await db.fetch_all("SELECT * FROM agents ORDER BY priority DESC, created_at DESC")

            result = []
            for agent_data in agents:
                agent_id = agent_data["id"]

                # Fetch related data inline (avoids N+1 from calling self.get)
                mcp_servers = await db.fetch_all(
                    "SELECT server_id, enabled FROM agent_mcp_servers WHERE agent_id = ? AND enabled = 1",
                    (agent_id,)
                )
                tools = await db.fetch_all(
                    "SELECT tool_name FROM agent_tools WHERE agent_id = ?",
                    (agent_id,)
                )

                from app.database.skill_repository import SkillRepository
                skill_repo = SkillRepository(db)
                skills = await skill_repo.get_agent_skills(agent_id)
                skill_names = [skill.name for skill in skills]

                agent = AgentResponse(
                    id=agent_data["id"],
                    name=agent_data["name"],
                    description=agent_data.get("description", ""),
                    type=AgentType(agent_data.get("type", "custom")),
                    execution_mode=agent_data.get("execution_mode", "plan"),
                    system_prompt=agent_data.get("system_prompt", ""),
                    model=agent_data.get("model"),
                    temperature=agent_data.get("temperature"),
                    max_tokens=agent_data.get("max_tokens"),
                    enabled=bool(agent_data.get("enabled", 1)),
                    priority=agent_data.get("priority", 0),
                    created_at=datetime.fromisoformat(agent_data["created_at"]) if agent_data.get("created_at") else datetime.utcnow(),
                    updated_at=datetime.fromisoformat(agent_data["updated_at"]) if agent_data.get("updated_at") else datetime.utcnow(),
                    usage_count=agent_data.get("usage_count", 0),
                    mcp_servers=[{"server_id": s["server_id"], "enabled": bool(s["enabled"])} for s in mcp_servers],
                    tools=[t["tool_name"] for t in tools],
                    skills=skill_names,
                    thinking_effort=agent_data.get("thinking_effort", "medium"),
                    max_react_steps=agent_data.get("max_react_steps", 15),
                    enable_long_term_memory=bool(agent_data.get("enable_long_term_memory", 0))
                )
                result.append(agent)

            return result

        finally:
            await db.disconnect()

    async def update(self, agent_id: str, update_data: AgentUpdate) -> Optional[AgentResponse]:
        """Update agent"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()

        try:
            current = await self.get(agent_id)
            if not current:
                return None

            updates = []
            params = []

            if update_data.name is not None:
                updates.append("name = ?")
                params.append(update_data.name)

            if update_data.description is not None:
                updates.append("description = ?")
                params.append(update_data.description)

            if update_data.type is not None:
                updates.append("type = ?")
                params.append(update_data.type.value if isinstance(update_data.type, AgentType) else update_data.type)

            if update_data.execution_mode is not None:
                updates.append("execution_mode = ?")
                params.append(update_data.execution_mode)

            if update_data.system_prompt is not None:
                updates.append("system_prompt = ?")
                params.append(update_data.system_prompt)

            if update_data.model is not None:
                updates.append("model = ?")
                params.append(update_data.model)

            if update_data.temperature is not None:
                updates.append("temperature = ?")
                params.append(update_data.temperature)

            if update_data.max_tokens is not None:
                updates.append("max_tokens = ?")
                params.append(update_data.max_tokens)

            if update_data.enabled is not None:
                updates.append("enabled = ?")
                params.append(1 if update_data.enabled else 0)

            if update_data.priority is not None:
                updates.append("priority = ?")
                params.append(update_data.priority)

            if hasattr(update_data, "thinking_effort") and update_data.thinking_effort is not None:
                updates.append("thinking_effort = ?")
                params.append(update_data.thinking_effort)

            if hasattr(update_data, "max_react_steps") and update_data.max_react_steps is not None:
                updates.append("max_react_steps = ?")
                params.append(update_data.max_react_steps)

            if hasattr(update_data, "enable_long_term_memory") and update_data.enable_long_term_memory is not None:
                updates.append("enable_long_term_memory = ?")
                params.append(1 if update_data.enable_long_term_memory else 0)

            if updates:
                updates.append("updated_at = ?")
                params.append(datetime.utcnow().isoformat())
                params.append(agent_id)

                query = f"UPDATE agents SET {', '.join(updates)} WHERE id = ?"
                await db.execute(query, tuple(params))

            if update_data.mcp_servers is not None:
                await db.execute("DELETE FROM agent_mcp_servers WHERE agent_id = ?", (agent_id,))
                for server_id in update_data.mcp_servers:
                    await db.execute("""
                    INSERT INTO agent_mcp_servers (id, agent_id, server_id, enabled)
                    VALUES (?, ?, ?, ?)
                    """, (str(uuid.uuid4()), agent_id, server_id, 1))

            if update_data.tools is not None:
                await db.execute("DELETE FROM agent_tools WHERE agent_id = ?", (agent_id,))
                for tool_config in update_data.tools:
                    if isinstance(tool_config, str):
                        tool_name = tool_config
                        permission = "optional"
                        description = ""
                    else:
                        tool_name = tool_config.get("tool_name", "")
                        permission = tool_config.get("permission", "optional")
                        description = tool_config.get("description", "")

                    if tool_name:
                        await db.execute("""
                        INSERT INTO agent_tools (id, agent_id, tool_name, permission, description)
                        VALUES (?, ?, ?, ?, ?)
                        """, (str(uuid.uuid4()), agent_id, tool_name, permission, description))

            if hasattr(update_data, "skills") and update_data.skills is not None:
                from app.database.skill_repository import SkillRepository
                from app.models.skill import AgentSkillLink

                skill_repo = SkillRepository(db)
                await db.execute("DELETE FROM agent_skills WHERE agent_id = ?", (agent_id,))

                for skill_name in update_data.skills:
                    skill = await skill_repo.get_skill_by_name(skill_name)
                    if skill:
                        link = AgentSkillLink(
                            agent_id=agent_id,
                            skill_id=skill.id,
                            enabled=True,
                            priority=0
                        )
                        await skill_repo.link_agent_skill(link)

            await db.commit()

        except Exception:
            await db.rollback()
            raise
        finally:
            await db.disconnect()

        # Post-commit: get updated agent and sync
        agent = await self.get(agent_id)
        if agent and hasattr(update_data, "skills") and update_data.skills is not None:
            await self._sync_agent_skills_to_registry(agent_id, update_data.skills)

        if agent:
            from app.services.agent_registry import agent_registry
            if agent.enabled:
                await agent_registry.register_existing_agent(agent)
            else:
                agent_registry.unregister(agent_id)

        return agent

    async def delete(self, agent_id: str) -> bool:
        """Delete agent"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()

        try:
            # Delete agent memories from SQLite
            await db.execute("DELETE FROM agent_memories WHERE agent_id = ?", (agent_id,))
            # Delete agent
            await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
            await db.commit()

            from app.services.agent_registry import agent_registry
            agent_registry.unregister(agent_id)

            # Delete agent memories from ChromaDB
            try:
                from app.services.vector_service import VectorService
                vector_service = VectorService()
                if vector_service.is_available():
                    try:
                        collection = vector_service.get_or_create_collection(agent_id)
                        vector_service.client.delete_collection(f"agent_{agent_id}")
                        logger.info(f"Deleted ChromaDB collection for agent {agent_id}")
                    except Exception as e:
                        logger.warning(f"Failed to delete ChromaDB collection for agent {agent_id}: {e}")
            except Exception:
                pass

            # Invalidate memory profile cache
            try:
                from app.services.agent_memory_service import agent_memory_service
                agent_memory_service._profile_cache.pop(agent_id, None)
            except Exception:
                pass

            return True

        except Exception:
            await db.rollback()
            raise
        finally:
            await db.disconnect()

    async def increment_usage(self, agent_id: str):
        """Increment agent usage count"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()

        try:
            await db.execute("UPDATE agents SET usage_count = usage_count + 1 WHERE id = ?", (agent_id,))
            await db.commit()
        finally:
            await db.disconnect()

    async def select_best_agent(
        self,
        message: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[AgentResponse]:
        """Select the best agent for the current task"""
        agents = await self.list(enabled_only=True)

        if not agents:
            return None

        return agents[0]


# Global agent service instance
agent_service = AgentService()
