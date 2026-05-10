"""Collaboration engine dispatcher - routes to appropriate collaboration mode"""
import json
import logging

from app.models.collaboration import CollaborationMode, IterationConfig, CollaborationResponse
from app.services.collaboration_service import collaboration_service
from app.services.collaboration.supervisor import SupervisorCollaboration
from app.services.collaboration.game import GameCollaboration
from app.services.collaboration.pipeline import PipelineCollaboration
from app.services.collaboration.voting import VotingCollaboration

logger = logging.getLogger(__name__)


class CollaborationEngine:
    """Main engine that dispatches to appropriate collaboration mode"""

    def __init__(self):
        self.modes = {
            CollaborationMode.SUPERVISOR: SupervisorCollaboration(),
            CollaborationMode.PIPELINE: PipelineCollaboration(),
            CollaborationMode.VOTING: VotingCollaboration(),
            CollaborationMode.ADVERSARIAL_GAME: GameCollaboration(),
        }

    async def execute(self, collab_id: str, input_text: str) -> dict:
        """Execute a collaboration"""
        collab = await collaboration_service.get(collab_id)
        if not collab:
            raise ValueError(f"Collaboration {collab_id} not found")

        if not collab.enabled:
            raise ValueError(f"Collaboration {collab_id} is disabled")

        mode_handler = self.modes.get(collab.mode)
        if not mode_handler:
            raise ValueError(f"Unsupported collaboration mode: {collab.mode}")

        # Check if iteration is enabled
        iteration_config = IterationConfig(**collab.config_json.get("iteration", {}))
        if iteration_config.enabled:
            task = await mode_handler.execute_with_iteration(collab, input_text)
        else:
            task = await mode_handler.execute(collab, input_text)

        return {
            "task_id": task.id,
            "collaboration_id": collab_id,
            "input": task.input,
            "output": task.output,
            "status": task.status.state.value,
            "messages": [m.dict() for m in task.messages],
            "started_at": task.created_at,
            "completed_at": task.updated_at if task.status.state.value in ["completed", "failed"] else None
        }

    async def execute_stream(self, collab: CollaborationResponse, input_text: str):
        """Execute a collaboration with SSE streaming, handling iteration if enabled."""
        mode_handler = self.modes.get(collab.mode)
        if not mode_handler:
            raise ValueError(f"Unsupported collaboration mode: {collab.mode}")

        iteration_config = IterationConfig(**collab.config_json.get("iteration", {}))
        if iteration_config.enabled:
            async for event in mode_handler.execute_stream_with_iteration(collab, input_text):
                yield event
        else:
            async for event in mode_handler.execute_stream(collab, input_text):
                yield event


# Global collaboration engine instance
collaboration_engine = CollaborationEngine()
