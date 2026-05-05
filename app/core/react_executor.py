"""ReAct mode executor - backward-compatible wrapper around ReActCotExecutor.

This module provides the original ReActExecutor interface (with events like
"thinking_start", "thinking", "action_start", "observation", "complete")
by delegating to ReActCotExecutor and translating its event format.
"""
import logging
from typing import Dict, List, Any, Optional, AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ExecutionRecord:
    """Single execution record"""
    step: int
    thought: str
    action: Dict[str, Any]
    observation: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


class ReActExecutor:
    """ReAct mode executor using official Volcengine tool_calls mechanism.

    Delegates to ReActCotExecutor and translates events to the original
    ReActExecutor event format for backward compatibility.
    """

    def __init__(
        self,
        agent_config: Optional[Dict[str, Any]] = None,
        llm_client=None,  # Accepted for API compatibility but not used
    ):
        self.agent_config = agent_config or {}
        self.max_steps = self.agent_config.get("max_react_steps", 15)
        self.execution_history: List[ExecutionRecord] = []

    async def execute(
        self,
        task: str,
        conversation_history: Optional[List[Dict]] = None,
        deep_thinking: bool = True
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute task using ReAct with official tool_calls.

        Yields events in the original ReActExecutor format for backward compatibility.
        """
        from app.core.react_cot_executor import ReActCotExecutor

        executor = ReActCotExecutor(agent_config=self.agent_config)
        self.execution_history = []

        current_step = 0
        current_thought = ""
        current_action = {}
        thinking_started = False

        async for event in executor.execute(
            task,
            conversation_history=conversation_history,
            deep_thinking=deep_thinking
        ):
            event_type = event.get("type")

            if event_type == "cot_step_start":
                step = event.get("step", 1)
                yield {"type": "thinking_start", "message": "深度思考中..."}

            elif event_type == "cot_phase":
                phase = event.get("phase")
                if phase == "thinking" and not thinking_started:
                    thinking_started = True
                    yield {"type": "phase", "phase": "thought"}

            elif event_type == "cot_thinking":
                content = event.get("content", "")
                current_thought += content
                step = event.get("step", 1)
                if step != current_step:
                    current_step = step
                yield {"type": "thinking", "message": content}

            elif event_type == "cot_action":
                tool_name = event.get("tool_name", "")
                tool_args = event.get("tool_args", {})
                current_action = {"tool_calls": [{"function": {"name": tool_name, "arguments": str(tool_args)}}]}

                # Record to history
                self.execution_history.append(
                    ExecutionRecord(
                        step=current_step,
                        thought=current_thought,
                        action=current_action,
                        observation=""
                    )
                )

                yield {
                    "type": "action_start",
                    "step": current_step,
                    "tool_name": tool_name,
                    "arguments": tool_args,
                    "thought": current_thought
                }

            elif event_type == "cot_observation":
                result = event.get("result", {})
                if self.execution_history:
                    self.execution_history[-1].observation = str(result)

                yield {
                    "type": "observation",
                    "step": current_step,
                    "tool_name": "",
                    "result": result
                }

            elif event_type == "cot_complete":
                message = event.get("message", "")
                yield {"type": "thinking_end", "message": "思考完成"}
                yield {"type": "complete", "message": message}

            elif event_type == "error":
                yield {"type": "error", "message": event.get("message", "Unknown error")}

            elif event_type == "end":
                yield {"type": "end"}
