"""Execution strategy router - routes to LLM with deep thinking support"""
import logging
from typing import Optional, Dict, List, Any, AsyncGenerator
from datetime import datetime

from app.config import settings
from app.services.llm_service import llm_service

logger = logging.getLogger(__name__)


class ExecutionStrategyRouter:
    """Routes execution to LLM with deep thinking support"""

    def __init__(self):
        """Initialize router"""
        self.llm_service = None

    def set_llm_client(self, client):
        """Set LLM client for executors

        Args:
            client: LLM client
        """
        # Load LLM service
        self.llm_service = llm_service

    async def execute(
        self,
        task: str,
        agent_config: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict]] = None,
        deep_thinking: bool = False
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute task using Volcengine LLM with deep thinking

        Args:
            task: User task
            agent_config: Agent configuration
            conversation_history: Conversation history
            deep_thinking: Enable deep thinking mode

        Yields:
            Execution events with thinking support
        """
        logger.info(f"Executing task with deep_thinking={deep_thinking}")

        # Use agent's model config if available
        model = None
        temperature = None
        max_tokens = None
        system_prompt = None

        if agent_config:
            model = agent_config.get("model") or None
            temperature = agent_config.get("temperature")
            max_tokens = agent_config.get("max_tokens")
            system_prompt = agent_config.get("system_prompt")

        # Prepare messages
        messages = []

        # Add conversation history
        if conversation_history:
            messages.extend(conversation_history)

        # Inject time reminder after history, before current message
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        messages.append({
            "role": "system",
            "content": f"【提醒】当前日期时间：{current_time}，请基于此时间回答问题。"
        })

        # Add current task (skip if already the last message in history)
        last_msg = conversation_history[-1] if conversation_history else None
        if not (last_msg and last_msg.get("role") == "user" and last_msg.get("content") == task):
            messages.append({
                "role": "user",
                "content": task
            })

        logger.info(f"Calling LLM with {len(messages)} messages, deep_thinking={deep_thinking}")

        # Call LLM with streaming
        thinking_started = False
        full_response = ""

        # Get reasoning_effort from agent config or use default
        reasoning_effort = "medium"
        if agent_config:
            reasoning_effort = agent_config.get("reasoning_effort", "medium")

        try:
            async for content, thinking in self.llm_service._chat_completion_stream_with_thinking(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                enable_thinking=deep_thinking,
                reasoning_effort=reasoning_effort
            ):
                if thinking is not None:
                    # Thinking content
                    if not thinking_started:
                        thinking_started = True
                        yield {
                            "type": "thinking_start",
                            "message": "开始思考..."
                        }

                    yield {
                        "type": "thinking",
                        "content": thinking
                    }
                elif content is not None:
                    # Regular content
                    if thinking_started and not full_response:
                        # First content after thinking, signal thinking end
                        yield {
                            "type": "thinking_end",
                            "message": "思考完成"
                        }

                    full_response += content
                    yield {
                        "type": "message",
                        "content": content
                    }
                    # 让出控制权，确保 WebSocket 能及时发送
                    await asyncio.sleep(0)

            # Send thinking_end if needed
            if thinking_started and not full_response:
                yield {
                    "type": "thinking_end",
                    "message": "思考完成"
                }

            # Send end event
            yield {
                "type": "end"
            }

            logger.info("Execution complete")

        except Exception as e:
            logger.error(f"Error in execution: {e}", exc_info=True)
            yield {
                "type": "error",
                "message": f"Execution error: {str(e)}"
            }


# Global instance
strategy_router = ExecutionStrategyRouter()
