"""Collaboration Service - manages collaboration configurations and templates"""
import uuid
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from app.utils.timezone import beijing_now

from app.models.collaboration import (
    CollaborationCreate, CollaborationUpdate, CollaborationResponse,
    CollaborationMode, CollaborationAgentConfig, TEMPLATES
)
from app.database.connection import DatabaseConnection
from app.config import settings
from app.services.agent_service import agent_service

logger = logging.getLogger(__name__)


class CollaborationService:
    """Service for managing collaboration configurations"""

    async def create(self, data: CollaborationCreate) -> CollaborationResponse:
        """Create a new collaboration configuration"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()

        try:
            collab_id = str(uuid.uuid4())
            now = beijing_now().isoformat()

            # Insert collaboration
            await db.execute("""
            INSERT INTO collaborations (id, name, description, mode, config_json, enabled, created_at, updated_at, usage_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                collab_id,
                data.name,
                data.description,
                data.mode.value if hasattr(data.mode, 'value') else str(data.mode),
                self._serialize_config(data.config_json),
                1 if data.enabled else 0,
                now,
                now,
                0
            ))

            # Insert collaboration agents
            for agent_config in data.agents:
                await db.execute("""
                INSERT INTO collaboration_agents (id, collaboration_id, agent_id, role, priority, is_human, config_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(uuid.uuid4()),
                    collab_id,
                    agent_config.agent_id,
                    agent_config.role,
                    agent_config.priority,
                    1 if agent_config.is_human else 0,
                    self._serialize_config(agent_config.config_json)
                ))

            await db.commit()
            return await self.get(collab_id)

        finally:
            await db.disconnect()

    async def get(self, collab_id: str) -> Optional[CollaborationResponse]:
        """Get collaboration by ID"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()

        try:
            # Get collaboration
            row = await db.fetch_one("SELECT * FROM collaborations WHERE id = ?", (collab_id,))
            if not row:
                return None

            # Get collaboration agents
            agents_rows = await db.fetch_all(
                "SELECT * FROM collaboration_agents WHERE collaboration_id = ? ORDER BY priority",
                (collab_id,)
            )

            agents = []
            for agent_row in agents_rows:
                agents.append(CollaborationAgentConfig(
                    agent_id=agent_row["agent_id"],
                    role=agent_row["role"],
                    priority=agent_row["priority"],
                    is_human=bool(agent_row.get("is_human", 0)),
                    config_json=self._deserialize_config(agent_row.get("config_json"))
                ))

            return CollaborationResponse(
                id=row["id"],
                name=row["name"],
                description=row.get("description", ""),
                mode=CollaborationMode(row["mode"]),
                config_json=self._deserialize_config(row.get("config_json")),
                enabled=bool(row.get("enabled", 1)),
                agents=agents,
                created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else beijing_now(),
                updated_at=datetime.fromisoformat(row["updated_at"]) if row.get("updated_at") else beijing_now(),
                usage_count=row.get("usage_count", 0)
            )

        finally:
            await db.disconnect()

    async def list(self, enabled_only: bool = False) -> List[CollaborationResponse]:
        """List all collaborations"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()

        try:
            if enabled_only:
                rows = await db.fetch_all("SELECT id FROM collaborations WHERE enabled = 1 ORDER BY created_at DESC")
            else:
                rows = await db.fetch_all("SELECT id FROM collaborations ORDER BY created_at DESC")

            result = []
            for row in rows:
                collab = await self.get(row["id"])
                if collab:
                    result.append(collab)
            return result

        finally:
            await db.disconnect()

    async def update(self, collab_id: str, data: CollaborationUpdate) -> Optional[CollaborationResponse]:
        """Update collaboration configuration"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()

        try:
            # Check if exists
            existing = await db.fetch_one("SELECT id FROM collaborations WHERE id = ?", (collab_id,))
            if not existing:
                return None

            # Build update query
            updates = []
            params = []

            if data.name is not None:
                updates.append("name = ?")
                params.append(data.name)

            if data.description is not None:
                updates.append("description = ?")
                params.append(data.description)

            if data.mode is not None:
                updates.append("mode = ?")
                params.append(data.mode.value if hasattr(data.mode, 'value') else str(data.mode))

            if data.config_json is not None:
                updates.append("config_json = ?")
                params.append(self._serialize_config(data.config_json))

            if data.enabled is not None:
                updates.append("enabled = ?")
                params.append(1 if data.enabled else 0)

            if updates:
                updates.append("updated_at = ?")
                params.append(beijing_now().isoformat())
                params.append(collab_id)

                query = f"UPDATE collaborations SET {', '.join(updates)} WHERE id = ?"
                await db.execute(query, tuple(params))

            # Update agents if provided
            if data.agents is not None:
                # Delete old agents
                await db.execute("DELETE FROM collaboration_agents WHERE collaboration_id = ?", (collab_id,))

                # Insert new agents
                for agent_config in data.agents:
                    await db.execute("""
                    INSERT INTO collaboration_agents (id, collaboration_id, agent_id, role, priority, is_human, config_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        str(uuid.uuid4()),
                        collab_id,
                        agent_config.agent_id,
                        agent_config.role,
                        agent_config.priority,
                        1 if agent_config.is_human else 0,
                        self._serialize_config(agent_config.config_json)
                    ))

            await db.commit()
            return await self.get(collab_id)

        finally:
            await db.disconnect()

    async def delete(self, collab_id: str) -> bool:
        """Delete collaboration configuration"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()

        try:
            await db.execute("DELETE FROM collaborations WHERE id = ?", (collab_id,))
            await db.commit()
            return True

        finally:
            await db.disconnect()

    async def increment_usage(self, collab_id: str):
        """Increment usage count"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()

        try:
            await db.execute("UPDATE collaborations SET usage_count = usage_count + 1 WHERE id = ?", (collab_id,))
            await db.commit()

        finally:
            await db.disconnect()

    def list_templates(self) -> Dict[str, Any]:
        """List all available templates"""
        return {
            key: {
                "name": t.name,
                "description": t.description,
                "mode": t.mode.value,
                "default_agents": t.default_agents,
                "default_config": t.default_config
            }
            for key, t in TEMPLATES.items()
        }

    async def create_from_template(self, template_key: str, name: str, agent_ids: Dict[str, str],
                                      agent_roles: Dict[str, str] = None) -> CollaborationResponse:
        """Create a collaboration from a template

        agent_ids uses index-based keys: {"0": "agent_id_1", "1": "agent_id_2", ...}
        agent_roles (optional) overrides roles per slot: {"0": "supervisor", "1": "child", ...}
        If agent_roles is not provided, roles are taken from template default_agents.
        If agent_ids has more slots than template default_agents, remaining slots default to
        the last role in the template (e.g. "child" for supervisor mode).
        """
        if template_key not in TEMPLATES:
            raise ValueError(f"Template {template_key} not found")

        template = TEMPLATES[template_key]

        # Build agents list from submitted slots
        agents = []
        num_slots = len(agent_ids)

        for i in range(num_slots):
            agent_id = agent_ids.get(str(i))
            if not agent_id:
                raise ValueError(f"Missing agent_id for slot {i}")

            # Determine role: explicit override > template default > last template role
            if agent_roles and str(i) in agent_roles:
                role = agent_roles[str(i)]
            elif i < len(template.default_agents):
                role = template.default_agents[i]["role"]
            else:
                # Extra slots beyond template default get the last template role
                role = template.default_agents[-1]["role"]

            # Verify agent exists
            agent = await agent_service.get(agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")

            agents.append(CollaborationAgentConfig(
                agent_id=agent_id,
                role=role,
                priority=0,
                config_json={}
            ))

        # Create collaboration
        create_data = CollaborationCreate(
            name=name,
            description=template.description,
            mode=template.mode,
            agents=agents,
            config_json=template.default_config,
            enabled=True
        )

        return await self.create(create_data)

    def _serialize_config(self, config: Optional[Dict]) -> str:
        """Serialize config dict to JSON string"""
        if config is None:
            return "{}"
        import json
        return json.dumps(config, ensure_ascii=False)

    def _deserialize_config(self, config_str: Optional[str]) -> Dict:
        """Deserialize JSON string to config dict"""
        if not config_str:
            return {}
        import json
        try:
            return json.loads(config_str)
        except:
            return {}


# Global collaboration service instance
collaboration_service = CollaborationService()
