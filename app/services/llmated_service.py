"""LLM service for interacting with Anthropic Claude API with MCP tool calling"""
from anthropic import AsyncAnthropic
from typing import Optional, AsyncGenerator, List, Dict, Any
import logging
import json
from app.config import settings
from app.services.mcp_service import mcp_tool_manager

logger = logging.getLogger(__name__)


class LLMService:
    """Service for interacting with LLM with tool calling support"""

    def __init__(self, api_key: Optional[str] = None, enable_tools: bool = True):
        """Initialize LLM service

        Args:
            api_key: Anthropic API key (optional, uses settings if not provided)
            enable_tools: Enable tool calling support
        """
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        self.model = settings.LLM_MODEL
        self.temperature = settings.LLM_TEMPERATURE
        self.max_tokens = settings.LLM_MAX_TOKENS
        self.enable_tools = enable_tools

        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEY not configured")

        self.client = AsyncAnthropic(api_key=self.api_key) if self.api_key else None

    async def chat(
        self,
        message: str,
        conversation_history: Optional[list[dict]] = None,
        use_tools: bool = None
    ) -> str:
        """Send chat message to LLM

        Args:
            message: User message
            conversation_history: Previous conversation messages
            use_tools: Enable tool calling for this request

        Returns:
            LLM response
        """
        if not self.client:
            raise ValueError("LLM client not configured. Please set ANTHROPIC_API_KEY.")

        should_use_tools = (use_tools if use_tools is not None else self.enable_tools) and self._has_tools()

        messages = self._build_messages(message, conversation_history)

        try:
            if should_use_tools:
                return await self._chat_with_tools(messages)
            else:
                response = await self.client.messages.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature
                )
                return response.content[0].text

        except Exception as e:
            logger.error(f"Error calling LLM: {e}")
            raise

    async def chat_stream(
        self,
        message: str,
        conversation_history: Optional[list[dict]] = None,
        use_tools: bool = None
    ) -> AsyncGenerator[str, None]:
        """Send chat message to LLM with streaming response

        Args:
            message: User message
            conversation_history: Previous conversation messages
            use_tools: Enable tool calling for this request

        Yields:
            Stream of text chunks
        """
        if not self.client:
            raise ValueError("LLM client not configured. Please set ANTHROPIC_API_KEY.")

        should_use_tools = (use_tools if use_tools is not None else self.enable_tools) and self._has_tools()

        messages = self._build_messages(message, conversation_history)

        try:
            if should_use_tools:
                async for chunk in self._chat_stream_with_tools(messages):
                    yield chunk
            else:
                async with self.client.messages.stream(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature
                ) as stream:
                    async for text in stream.text_stream:
                        yield text

        except Exception as e:
            logger.error(f"Error calling LLM stream: {e}")
            raise

    async def _chat_with_tools(self, messages: List[Dict]) -> str:
        """Chat with tool calling support

        Args:
            messages: Conversation messages

        Returns:
            LLM response with tool results
        """
        tools = self._get_anthropic_tools()

        # Add system message with tool descriptions
        system_message = self._get_system_message()

        max_iterations = 5  # Prevent infinite loops
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            response = await self.client.messages.create(
                model=self.model,
                system=system_message,
                messages=messages,
                tools=tools,
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )

            # Check if model wants to use tools
            stop_reason = response.stop_reason

            if stop_reason == "tool_use":
                # Handle tool use
                for block in response.content:
                    if block.type == "tool_use":
                        tool_name = block.name
                        tool_input = block.input

                        logger.info(f"LLM requesting tool: {tool_name}")
                        logger.debug(f"Tool input: {tool_input}")

                        try:
                            # Execute tool
                            tool_result = await mcp_tool_manager.call_tool(tool_name, tool_input)

                            # Convert result to string
                            if isinstance(tool_result, (dict, list)):
                                result_str = json.dumps(tool_result, ensure_ascii=False, indent=2)
                            else:
                                result_str = str(tool_result)

                            logger.info(f"Tool result: {result_str[:200]}...")

                            # Add tool use and result to messages
                            messages.append({
                                "role": "assistant",
                                "content": [block]
                            })
                            messages.append({
                                "role": "user",
                                "content": [{
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": result_str
                                }]
                            })

                        except Exception as e:
                            logger.error(f"Error executing tool {tool_name}: {e}")
                            error_msg = f"Error executing tool {tool_name}: {str(e)}"
                            messages.append({
                                "role": "assistant",
                                "content": [block]
                            })
                            messages.append({
                                "role": "user",
                                "content": [{
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": error_msg
                                }]
                            })

                # Continue loop to get final response
                continue

            else:
                # No more tool calls, return text response
                text_blocks = [block.text for block in response.content if block.type == "text"]
                return "".join(text_blocks)

        return "Maximum iterations reached. Please try again."

    async def _chat_stream_with_tools(self, messages: List[Dict]) -> AsyncGenerator[str, None]:
        """Chat with streaming and tool calling support

        Args:
            messages: Conversation messages

        Yields:
            Stream of text chunks
        """
        tools = self._get_anthropic_tools()
        system_message = self._get_system_message()

        max_iterations = 5
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            response = await self.client.messages.create(
                model=self.model,
                system=system_message,
                messages=messages,
                tools=tools,
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )

            stop_reason = response.stop_reason

            if stop_reason == "tool_use":
                # Handle tool use silently (don't stream)
                for block in response.content:
                    if block.type == "tool_use":
                        tool_name = block.name
                        tool_input = block.input

                        logger.info(f"LLM requesting tool: {tool_name}")

                        try:
                            tool_result = await mcp_tool_manager.call_tool(tool_name, tool_input)

                            if isinstance(tool_result, (dict, list)):
                                result_str = json.dumps(tool_result, ensure_ascii=False, indent=2)
                            else:
                                result_str = str(tool_result)

                            messages.append({
                                "role": "assistant",
                                "content": [block]
                            })
                            messages.append({
                                "role": "user",
                                "content": [{
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": result_str
                                }]
                            })

                        except Exception as e:
                            logger.error(f"Error executing tool {tool_name}: {e}")
                            error_msg = f"Error executing tool {tool_name}: {str(e)}"
                            messages.append({
                                "role": "assistant",
                                "content": [block]
                            })
                            messages.append({
                                "role": "user",
                                "content": [{
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": error_msg
                                }]
                            })

                yield "[使用工具�?..] "
                continue

            else:
                # Stream text response
                text_blocks = [block.text for block in response.content if block.type == "text"]
                text = "".join(text_blocks)
                yield text
                break

    def _has_tools(self) -> bool:
        """Check if tools are available

        Returns:
            True if tools available
        """
        return mcp_tool_manager.mcp_service.is_connected() or len(mcp_tool_manager.local_services) > 0

    def _get_anthropic_tools(self) -> List[Dict]:
        """Get tools in Anthropic format

        Returns:
            List of tool definitions
        """
        tools = []

        # Get all tools from MCP and local services
        all_tools = mcp_tool_manager.all_tools

        for tool_name, tool in all_tools.items():
            tools.append({
                "name": tool_name,
                "description": tool.description,
                "input_schema": tool.input_schema
            })

        return tools

    def _get_system_message(self) -> str:
        """Get system message with tool descriptions

        Returns:
            System message
        """
        if not self._has_tools():
            return "You are a helpful AI assistant."

        tool_descriptions = mcp_tool_manager.get_tools_description()

        return f"""You are a helpful AI assistant with access to tools.

Available tools:
{tool_descriptions}

When you need to use a tool, respond with a tool_use block. After receiving the tool result, continue the conversation naturally.
Use tools when they can help answer the user's question or complete the requested task."""

    def _build_messages(
        self,
        message: str,
        conversation_history: Optional[list[dict]] = None
    ) -> list[dict]:
        """Build message list for LLM API

        Args:
            message: Current user message
            conversation_history: Previous messages

        Returns:
            List of messages in Anthropic format
        """
        messages = []

        if conversation_history:
            for msg in conversation_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")

                # Preserve tool results if present
                if isinstance(content, list):
                    messages.append({"role": role, "content": content})
                elif role in ["user", "assistant"]:
                    messages.append({"role": role, "content": content})

        # Add current message
        messages.append({"role": "user", "content": message})

        return messages

    async def _chat_completion(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> str:
        """Send chat completion with custom parameters

        Args:
            messages: Conversation messages
            model: Model override
            temperature: Temperature override
            max_tokens: Max tokens override

        Returns:
            LLM response text
        """
        if not self.client:
            raise ValueError("LLM client not configured. Please set ANTHROPIC_API_KEY.")

        try:
            logger.info(f"Calling LLM API: model={model or self.model}, messages={len(messages)}")

            response = await self.client.messages.create(
                model=model or self.model,
                messages=messages,
                max_tokens=max_tokens or self.max_tokens,
                temperature=temperature if temperature is not None else self.temperature
            )

            logger.info(f"LL LLM API response received, content blocks: {len(response.content)}")

            # Extract text from response
            text_blocks = [block.text for block in response.content if block.type == "text"]
            result = "".join(text_blocks)

            logger.info(f"Extracted {len(result)} characters from response")
            return result

        except Exception as e:
            logger.error(f"LLM API call failed: {e}", exc_info=True)
            raise

    def is_configured(self) -> bool:
        """Check if LLM service is properly configured

        Returns:
            True if configured
        """
        return bool(self.api_key)


# Global LLM service instance
llm_service = LLMService()
