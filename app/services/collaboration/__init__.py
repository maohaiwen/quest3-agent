"""Collaboration engine - multi-agent collaboration patterns"""

from app.services.collaboration.base import BaseCollaborationMode
from app.services.collaboration.supervisor import SupervisorCollaboration
from app.services.collaboration.game import GameCollaboration
from app.services.collaboration.pipeline import PipelineCollaboration
from app.services.collaboration.voting import VotingCollaboration
from app.services.collaboration.engine import collaboration_engine, CollaborationEngine

__all__ = [
    "BaseCollaborationMode",
    "SupervisorCollaboration",
    "GameCollaboration",
    "PipelineCollaboration",
    "VotingCollaboration",
    "CollaborationEngine",
    "collaboration_engine",
]
