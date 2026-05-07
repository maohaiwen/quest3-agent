"""LLM service for interacting with Volcengine SDK with deep thinking support"""
from typing import Optional, AsyncGenerator, List, Dict, Any, Tuple
import logging
import asyncio
import concurrent.futures
import threading
from queue import Queue
from app.config import settings
from app.services.mcp_service import mcp_tool_manager

try:
    from volcenginesdkarkruntime import Ark
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("volcengine-python-sdk not installed. Run: pip install volcengine-python-sdk[ark]")
    Ark = None

logger = logging.getLogger(__name__)


class LLMService:
    """Service for interacting with Volcengine LLM with deep thinking support"""

    def __init__(self, api_key: Optional[str] = None, enable_tools: bool = True):
        """Initialize LLM service

        Args:
            api_key: Volcengine API key (optional, uses settings if not provided)
            enable_tools: Enable tool calling support
        """
        self.api_key = api_key or settings.VOLCENGINE_API_KEY
        self.model = getattr(settings, 'VOLCENGINE_MODEL', 'DeepSeek-V3.2')
        self.temperature = settings.LLM_TEMPERATURE
        self.max_tokens = settings.LLM_MAX_TOKENS
        self.enable_tools = enable_tools

        if not self.api_key:
            logger.warning("VOLCENGINE_API_KEY not configured")

        # Initialize Volcengine client
        self.volc_client = None
        if Ark and self.api_key:
            volc_base_url = getattr(settings, 'VOLCENGINE_BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3')
            self.volc_client = Ark(base_url=volc_base_url, api_key=self.api_key)
            logger.info(f"Volcengine client initialized with model: {self.model}")

    async def chat(
        self,
        message: str,
        conversation_history: Optional[List[Dict]] = None,
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
        if not self.volc_client:
            raise ValueError("Volcengine client not configured. Please set VOLCENGINE_API_KEY.")

        should_use_tools = (use_tools if use_tools is not None else self.enable_tools) and self._has_tools()

        messages = self._build_messages(message, conversation_history)

        try:
            if should_use_tools:
                # TODO: Implement tool calling with Volcengine
                return await self._chat_with_tools(messages)
            else:
                response = await self._chat_completion(messages)
                return response

        except Exception as e:
            logger.error(f"Error calling LLM: {e}", exc_info=True)
            raise

    async def chat_stream(
        self,
        message: str,
        conversation_history: Optional[List[Dict]] = None,
        use_tools: bool = None,
        deep_thinking: bool = False,
        reasoning_effort: str = "medium"
    ) -> AsyncGenerator[str, None]:
        """Send chat message to LLM with streaming response

        Args:
            message: User message
            conversation_history: Previous conversation messages
            use_tools: Enable tool calling for this request
            deep_thinking: Enable deep thinking mode
            reasoning_effort: Reasoning effort level (minimal/low/medium/high)

        Yields:
            Stream of text chunks
        """
        if not self.volc_client:
            raise ValueError("Volcengine client not configured. Please set VOLCENGINE_API_KEY.")

        should_use_tools = (use_tools if use_tools is not None else self.enable_tools) and self._has_tools()

        messages = self._build_messages(message, conversation_history)

        try:
            if deep_thinking:
                # Use streaming with thinking support
                thinking_started = False

                async for content, thinking in self._chat_completion_stream_with_thinking(
                    messages,
                    enable_thinking=True,
                    reasoning_effort=reasoning_effort
                ):
                    if thinking is not None:
                        # Thinking content - yield with special marker
                        if not thinking_started:
                            yield "[THINKING_START]"
                            thinking_started = True
                        yield thinking
                    elif content is not None:
                        # Regular content
                        if thinking_started:
                            yield "[THINKING_END]"
                        yield content
            else:
                # Regular streaming without thinking
                async for content in self._chat_completion_stream(messages):
                    yield content

        except Exception as e:
            logger.error(f"Error calling LLM stream: {e}", exc_info=True)
            raise

    async def _chat_completion(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        max_continuations: int = 5
    ) -> str:
        """Send chat completion (non-streaming) with auto-continuation on truncation.

        When the LLM response is truncated (finish_reason=length), automatically
        sends a "continue" message to get the rest of the output, up to
        max_continuations times.

        Args:
            messages: Conversation messages
            model: Model override
            temperature: Temperature override
            max_tokens: Max tokens override
            system_prompt: Optional system prompt
            max_continuations: Max number of auto-continuation calls when truncated

        Returns:
            LLM response text (complete)
        """
        if not self.volc_client:
            raise ValueError("Volcengine client not configured. Please set VOLCENGINE_API_KEY.")

        try:
            effective_max_tokens = max_tokens if max_tokens is not None else self.max_tokens
            logger.info(f"Calling LLM API: model={model or self.model}, messages={len(messages)}, max_tokens={effective_max_tokens}")

            # Prepare API call parameters
            api_params = {
                "model": model or self.model,
                "messages": messages,
                "stream": False,
            }

            # Add temperature if provided
            if temperature is not None:
                api_params["temperature"] = temperature
            # Always pass max_tokens
            api_params["max_tokens"] = effective_max_tokens

            # Call API
            loop = asyncio.get_event_loop()
            full_response = ""
            current_messages = list(messages)  # copy to track conversation

            for attempt in range(max_continuations + 1):
                api_params["messages"] = current_messages
                result_text, finish_reason = await loop.run_in_executor(
                    None, self._sync_call_with_finish_reason, api_params
                )

                full_response += result_text
                logger.info(f"LLM call attempt {attempt + 1}: received {len(result_text)} chars, finish_reason={finish_reason}")

                if finish_reason != "length":
                    # Not truncated — we're done
                    break

                # Response was truncated — ask LLM to continue
                logger.warning(
                    f"LLM response truncated (attempt {attempt + 1}), "
                    f"auto-continuing... (total so far: {len(full_response)} chars)"
                )
                # Append the truncated assistant response and ask to continue
                current_messages.append({"role": "assistant", "content": result_text})
                current_messages.append({"role": "user", "content": "请继续输出，从你刚才中断的地方继续，不要重复已经输出的内容："})

            logger.info(f"LLM call complete, total {len(full_response)} characters after {min(attempt + 1, max_continuations + 1)} attempt(s)")
            return full_response

        except Exception as e:
            logger.error(f"LLM API call failed: {e}", exc_info=True)
            raise

    def _sync_call_with_finish_reason(self, api_params: Dict) -> Tuple[str, str]:
        """Synchronous API call for Volcengine, returns (text, finish_reason)

        Args:
            api_params: API parameters

        Returns:
            Tuple of (response_text, finish_reason)
        """
        completion = self.volc_client.chat.completions.create(**api_params)
        if completion.choices and completion.choices[0].message.content:
            finish_reason = completion.choices[0].finish_reason or "stop"
            if finish_reason == "length":
                logger.warning(f"LLM response truncated (finish_reason=length), max_tokens={api_params.get('max_tokens')}")
            return completion.choices[0].message.content, finish_reason
        return "", "stop"

    async def _chat_completion_stream(
        self,
        messages: List[Dict],
    ) -> AsyncGenerator[str, None]:
        """Stream chat completion (without thinking)

        Args:
            messages: Conversation messages

        Yields:
            Stream of text chunks
        """
        if not self.volc_client:
            raise ValueError("Volcengine client not configured. Please set VOLCENGINE_API_KEY.")

        # Create queues for streaming data
        chunk_queue = Queue()
        error_queue = Queue()

        def run_sync_stream():
            try:
                completion = self.volc_client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    stream=True
                )
                with completion:
                    for chunk in completion:
                        if chunk.choices and chunk.choices[0].delta.content:
                            content = chunk.choices[0].delta.content
                            if content:
                                chunk_queue.put(content)
                # Signal end of stream
                chunk_queue.put(None)  # Sentinel
            except Exception as e:
                logger.error(f"Error in sync stream: {e}", exc_info=True)
                error_queue.put(str(e))

        # Run streaming in background thread
        thread = threading.Thread(target=run_sync_stream, daemon=True)
        thread.start()

        # Stream chunks as they arrive
        loop = asyncio.get_event_loop()
        try:
            while True:
                try:
                    content = await loop.run_in_executor(None, chunk_queue.get, True, 0.1)
                except:
                    # Timeout, check if thread is still alive
                    if not thread.is_alive():
                        if not error_queue.empty():
                            error_msg = error_queue.get()
                            raise Exception(f"Stream error: {error_msg}")
                        try:
                            content = chunk_queue.get_nowait()
                        except:
                            break
                    continue

                if content is None:  # Sentinel
                    break
                yield content
        finally:
            if thread.is_alive():
                thread.join(timeout=1.0)

    async def _chat_completion_stream_with_thinking(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        enable_thinking: bool = True,
        reasoning_effort: str = "medium"
    ) -> AsyncGenerator[Tuple[str, Optional[str]], None]:
        """Stream chat completion with Volcengine thinking API

        Args:
            messages: Conversation messages
            model: Model override
            temperature: Temperature override
            max_tokens: Max tokens override
            system_prompt: Optional system prompt
            enable_thinking: Enable extended thinking
            reasoning_effort: Reasoning effort level (minimal/low/medium/high)

        Yields:
            Tuple of (content, thinking_content) - one will be non-None
        """
        if not self.volc_client:
            raise ValueError("Volcengine client not configured. Please set VOLCENGINE_API_KEY.")

        # Create queues for streaming data
        chunk_queue = Queue()
        error_queue = Queue()

        def run_sync_stream():
            try:
                api_params = {
                    "model": model or self.model,
                    "messages": messages,
                    "stream": True,
                }

                # Add temperature and max_tokens if provided
                if temperature is not None:
                    api_params["temperature"] = temperature
                if max_tokens is not None:
                    api_params["max_tokens"] = max_tokens

                # Add system prompt if provided
                if system_prompt is not None:
                    # Insert system prompt at beginning of messages
                    api_params["messages"] = [{"role": "system", "content": system_prompt}] + messages

                # Add thinking parameters
                if enable_thinking:
                    api_params["thinking"] = {"type": "enabled"}
                    api_params["reasoning_effort"] = reasoning_effort
                else:
                    api_params["thinking"] = {"type": "disabled"}

                logger.info(f"Volcengine API call with streaming: model={api_params['model']}, enable_thinking={enable_thinking}")

                completion = self.volc_client.chat.completions.create(**api_params)
                with completion:
                    for chunk in completion:
                        # Process reasoning_content (thinking)
                        if chunk.choices and chunk.choices[0].delta.reasoning_content:
                            content = chunk.choices[0].delta.reasoning_content
                            if content:
                                chunk_queue.put(("thinking", content))

                        # Process regular content (answer)
                        if chunk.choices and chunk.choices[0].delta.content:
                            content = chunk.choices[0].delta.content
                            if content:
                                chunk_queue.put(("content", content))

                # Signal end of stream
                chunk_queue.put(("end", None))

            except Exception as e:
                logger.error(f"Error in sync stream: {e}", exc_info=True)
                error_queue.put(str(e))

        # Run streaming in background thread
        thread = threading.Thread(target=run_sync_stream, daemon=True)
        thread.start()

        # Stream chunks as they arrive
        loop = asyncio.get_event_loop()
        try:
            while True:
                # Wait for chunk with timeout to check for errors
                try:
                    chunk = await loop.run_in_executor(None, chunk_queue.get, True, 0.1)
                except:
                    # Timeout, check if thread is still alive
                    if not thread.is_alive():
                        # Thread finished, check for errors
                        if not error_queue.empty():
                            error_msg = error_queue.get()
                            raise Exception(f"Stream error: {error_msg}")
                        # Try to get final chunk
                        try:
                            chunk = chunk_queue.get_nowait()
                        except:
                            break
                    # Thread still alive, continue waiting
                    else:
                        continue

                # Process chunk
                chunk_type, value = chunk

                # End of stream marker
                if chunk_type == "end":
                    break

                # Yield to caller
                if chunk_type == "thinking":
                    yield (None, value)
                elif chunk_type == "content":
                    yield (value, None)

        finally:
            # Wait for thread to finish
            if thread.is_alive():
                thread.join(timeout=1.0)

    async def _get_tools_format(self, allowed_tools: Optional[List[str]] = None, enabled_mcp_servers: Optional[List[str]] = None) -> List[Dict]:
        """Get tools in OpenAI format for Volcengine API

        Args:
            allowed_tools: Optional list of allowed tool names. If provided, only these tools are included.
            enabled_mcp_servers: Optional list of enabled MCP server IDs. If provided, only tools from these servers are included.

        Returns:
            List of tools in format: [{"type": "function", "function": {...}}]
        """
        from app.core.tool_manager import get_tool_manager

        tool_manager = get_tool_manager()
        tools = await tool_manager.get_tools_for_llm(
            enabled_mcp_servers=enabled_mcp_servers,
            allowed_tools=allowed_tools
        )

        return tools

    def _has_tools(self) -> bool:
        """Check if tools are available (sync version)

        Returns:
            True if tools available
        """
        from app.services.mcp_pool import mcp_client_pool
        # Just check local tools to avoid async issues
        return len(mcp_client_pool.local_tools) > 0

    def _build_messages(
        self,
        message: str,
        conversation_history: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """Build message list for LLM API

        Args:
            message: Current user message
            conversation_history: Previous messages

        Returns:
            List of messages
        """
        messages = []

        if conversation_history:
            for msg in conversation_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ["user", "assistant"]:
                    messages.append({"role": role, "content": content})

        # Add current message
        messages.append({"role": "user", "content": message})

        return messages

    async def _chat_completion_stream_with_tools(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        enable_thinking: bool = True,
        reasoning_effort: str = "medium"
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream chat completion with tool_calls support

        Args:
            messages: Conversation messages
            tools: List of tools in OpenAI format
            model: Model override
            temperature: Temperature override
            max_tokens: Max tokens override
            system_prompt: Optional system prompt
            enable_thinking: Enable extended thinking
            reasoning_effort: Reasoning effort level

        Yields:
            Dicts with type: "thinking", "content", "tool_calls", or "done"
        """
        if not self.volc_client:
            raise ValueError("Volcengine client not configured. Please set VOLCENGINE_API_KEY.")

        # Create queues for streaming data
        chunk_queue = Queue()
        error_queue = Queue()

        def run_sync_stream():
            try:
                api_params = {
                    "model": model or self.model,
                    "messages": messages,
                    "stream": True,
                }

                # Add temperature and max_tokens if provided
                if temperature is not None:
                    api_params["temperature"] = temperature
                if max_tokens is not None:
                    api_params["max_tokens"] = max_tokens

                # Add tools if provided
                if tools:
                    api_params["tools"] = tools

                # Add system prompt if provided
                if system_prompt is not None:
                    # Insert system prompt at beginning of messages if not already there
                    if not messages or messages[0].get("role") != "system":
                        api_params["messages"] = [{"role": "system", "content": system_prompt}] + messages

                # Add thinking parameters
                if enable_thinking:
                    api_params["thinking"] = {"type": "enabled"}
                    api_params["reasoning_effort"] = reasoning_effort
                else:
                    api_params["thinking"] = {"type": "disabled"}

                logger.info(f"Volcengine API call with tools: model={api_params['model']}, tools={len(tools) if tools else 0}")

                completion = self.volc_client.chat.completions.create(**api_params)
                with completion:
                    for chunk in completion:
                        # Process reasoning_content (thinking)
                        if chunk.choices and chunk.choices[0].delta.reasoning_content:
                            content = chunk.choices[0].delta.reasoning_content
                            if content:
                                chunk_queue.put({"type": "thinking", "content": content})

                        # Process regular content (answer)
                        if chunk.choices and chunk.choices[0].delta.content:
                            content = chunk.choices[0].delta.content
                            if content:
                                chunk_queue.put({"type": "content", "content": content})

                        # Process tool_calls
                        if chunk.choices and chunk.choices[0].delta.tool_calls:
                            tool_calls = chunk.choices[0].delta.tool_calls
                            if tool_calls:
                                # Convert tool_calls to list of dicts
                                tool_calls_list = []
                                for tc in tool_calls:
                                    tc_dict = {
                                        "index": tc.index,
                                        "id": tc.id,
                                        "type": tc.type,
                                        "function": {
                                            "name": tc.function.name,
                                            "arguments": tc.function.arguments
                                        }
                                    }
                                    tool_calls_list.append(tc_dict)
                                chunk_queue.put({"type": "tool_calls", "tool_calls": tool_calls_list})

                # Signal end of stream
                chunk_queue.put({"type": "done"})

            except Exception as e:
                logger.error(f"Error in sync stream with tools: {e}", exc_info=True)
                error_queue.put(str(e))

        # Run streaming in background thread
        thread = threading.Thread(target=run_sync_stream, daemon=True)
        thread.start()

        # Stream chunks as they arrive
        loop = asyncio.get_event_loop()
        try:
            while True:
                # Wait for chunk with timeout to check for errors
                try:
                    chunk = await loop.run_in_executor(None, chunk_queue.get, True, 0.1)
                except:
                    # Timeout, check if thread is still alive
                    if not thread.is_alive():
                        # Thread finished, check for errors
                        if not error_queue.empty():
                            error_msg = error_queue.get()
                            raise Exception(f"Stream error: {error_msg}")
                        # Try to get final chunk
                        try:
                            chunk = chunk_queue.get_nowait()
                        except:
                            break
                    # Thread still alive, continue waiting
                    else:
                        continue

                # Process chunk
                yield chunk

                # End of stream marker
                if chunk["type"] == "done":
                    break

        finally:
            # Wait for thread to finish
            if thread.is_alive():
                thread.join(timeout=1.0)

    def is_configured(self) -> bool:
        """Check if LLM service is properly configured

        Returns:
            True if configured
        """
        return bool(self.api_key) and bool(self.volc_client)

    def reconfigure(self):
        """Reconfigure LLM service with current settings values.

        Called when LLM-related settings are updated via the settings page.
        Rebuilds the Volcengine client with new API key / base URL / model.
        """
        self.api_key = settings.VOLCENGINE_API_KEY
        self.model = settings.VOLCENGINE_MODEL
        self.temperature = settings.LLM_TEMPERATURE
        self.max_tokens = settings.LLM_MAX_TOKENS

        if Ark and self.api_key:
            volc_base_url = getattr(settings, 'VOLCENGINE_BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3')
            self.volc_client = Ark(base_url=volc_base_url, api_key=self.api_key)
            logger.info(f"LLM service reconfigured with model: {self.model}")
        else:
            self.volc_client = None
            logger.warning("LLM service reconfigured but no API key available")


# Global LLM service instance
llm_service = LLMService()
