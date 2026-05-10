"""Base class for sandbox environments in multi-agent collaboration"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional

from app.core.tool_manager import ToolDefinition


class BaseSandbox(ABC):
    """Abstract base class for sandbox environments.

    A sandbox provides a shared, stateful environment for multi-agent
    collaboration. It injects tools and perspective into each agent,
    validates actions, and checks for game-over conditions.

    Lifecycle:
        on_task_start() → (per round) get_tools_for_agent() / get_state_view()
        / handle_action() / check_termination() → on_task_end()
    """

    @abstractmethod
    def get_tools_for_agent(self, agent_id: str, role: str) -> List[ToolDefinition]:
        """Return the list of sandbox tools available to a given agent.

        Different agents may receive different tools (e.g. only the
        participant whose turn it is gets a ``make_move`` tool).

        Args:
            agent_id: The agent's unique ID.
            role: The agent's role in the collaboration (e.g. "participant",
                "participant_0", "referee").

        Returns:
            List of ToolDefinition instances for this agent.
        """

    @abstractmethod
    def get_state_view(self, agent_id: str, role: str) -> str:
        """Return a textual description of the environment state visible to
        the given agent.

        This is injected into the agent's prompt so it can reason about the
        current state.  Implementations should respect information hiding
        (e.g. a card-game player should not see opponents' hands).

        Args:
            agent_id: The agent's unique ID.
            role: The agent's role in the collaboration.

        Returns:
            A human-readable string describing the visible state.
        """

    @abstractmethod
    async def handle_action(self, agent_id: str, role: str,
                            action: str, **kwargs) -> Dict[str, Any]:
        """Handle an action (tool call) from an agent.

        Args:
            agent_id: The agent's unique ID.
            role: The agent's role.
            action: The tool name that was called.
            **kwargs: The tool's arguments.

        Returns:
            A dict with at least a ``success`` key (bool).  On failure,
            include an ``error`` key with a description.
        """

    @abstractmethod
    def check_termination(self) -> Optional[Dict[str, Any]]:
        """Check whether the game / environment has reached a terminal state.

        Returns:
            None if the game is still in progress, or a dict with
            ``game_over`` (True), ``winner`` (optional str), and
            ``reason`` (str) if the game has ended.
        """

    def on_task_start(self, agents: List[Dict[str, Any]]) -> None:
        """Called when a collaboration task starts.

        Use this to set up initial state and map agents to roles.

        Args:
            agents: List of dicts with ``agent_id`` and ``role`` keys.
        """
        pass

    def on_task_end(self) -> None:
        """Called when the collaboration task ends.  Use for cleanup."""
        pass

    def get_action_hint(self, agent_id: str, role: str) -> Optional[str]:
        """Return a short hint about how the agent should act in this sandbox.

        This is appended to the participant prompt so the agent knows how
        to interact with the sandbox (e.g. "use the make_move tool to play",
        "use the play_card tool to play a card").  Return None for no hint.

        Args:
            agent_id: The agent's unique ID.
            role: The agent's role in the collaboration.

        Returns:
            A short hint string, or None.
        """
        return None

    async def parse_action_output(self, agent_id: str, role: str,
                                  text: str) -> Optional[Dict[str, Any]]:
        """Parse an agent's free-text output and apply the action.

        Called when the agent did NOT use a sandbox tool call but instead
        described its action in natural language.  Subclasses should
        extract the move / action from the text and call
        ``handle_action`` internally.

        Returns:
            The result dict from ``handle_action``, or None if no action
            could be extracted.
        """
        return None

    def get_display_state(self) -> Dict[str, Any]:
        """Return the full environment state for frontend display.

        Override this to provide a dict with an ``html`` key containing
        a self-contained HTML fragment.  The frontend inserts it as-is
        without any sandbox-specific rendering code.

        Returns:
            A dict, e.g. ``{"html": "<div>...</div>"}``.
        """
        return {}

    def get_tools_for_llm(self, agent_id: str, role: str) -> List[Dict[str, Any]]:
        """Convenience: return tools in LLM format (function-calling schema).

        This wraps ``get_tools_for_agent`` and converts each
        ToolDefinition into the dict format expected by the LLM API.
        """
        tools = self.get_tools_for_agent(agent_id, role)
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]
