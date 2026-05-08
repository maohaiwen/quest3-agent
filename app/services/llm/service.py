"""LLM service facade — delegates to the configured provider"""
import logging
from typing import Optional, List, Dict, Any, Tuple, AsyncGenerator

from app.config import settings
from app.services.llm.providers.base import LLMProvider

logger = logging.getLogger(__name__)


def _create_provider(provider_name: str) -> Optional[LLMProvider]:
    """Factory: create a provider instance based on the provider name and current settings.

    All providers share the unified LLM_API_KEY / LLM_BASE_URL / LLM_MODEL fields,
    resolved via settings.effective_llm_*() which handles legacy per-provider keys.
    """
    api_key = settings.effective_llm_api_key()
    base_url = settings.effective_llm_base_url()
    model = settings.effective_llm_model()

    common_kwargs = {
        "api_key": api_key,
        "model": model,
        "base_url": base_url,
        "temperature": settings.LLM_TEMPERATURE,
        "max_tokens": settings.LLM_MAX_TOKENS,
    }

    if provider_name == "volcengine":
        from app.services.llm.providers.volcengine import VolcengineProvider
        return VolcengineProvider(**common_kwargs)
    elif provider_name == "deepseek":
        from app.services.llm.providers.deepseek import DeepSeekProvider
        return DeepSeekProvider(**common_kwargs)
    elif provider_name == "openai_compatible":
        from app.services.llm.providers.openai_compatible import OpenAICompatibleProvider
        return OpenAICompatibleProvider(**common_kwargs)
    else:
        logger.error(f"Unknown LLM provider: {provider_name}")
        return None


class LLMService:
    """Service for interacting with LLM providers.

    This is a facade that delegates all calls to the currently configured
    LLMProvider implementation. Switching providers only requires changing
    the LLM_PROVIDER setting.
    """

    def __init__(self, api_key: Optional[str] = None, enable_tools: bool = True):
        """Initialize LLM service.

        Args:
            api_key: Optional API key override (for backward compatibility).
                     When provided, uses volcengine provider with this key.
            enable_tools: Enable tool calling support
        """
        self.enable_tools = enable_tools
        self._override_api_key = api_key

        # Determine provider from settings
        provider_name = getattr(settings, "LLM_PROVIDER", "volcengine")

        # Backward compatibility: if explicit api_key is given, force volcengine
        if api_key and provider_name != "volcengine":
            logger.info(f"Explicit api_key provided, using volcengine provider")

        self.provider: Optional[LLMProvider] = _create_provider(provider_name)

        if self.provider and self.provider.is_configured():
            logger.info(f"LLM service initialized with provider: {provider_name}, model: {self.provider.model}")
        else:
            logger.warning(f"LLM provider '{provider_name}' not configured. Please set the appropriate API key.")

    @property
    def model(self) -> str:
        """Current default model name."""
        return self.provider.model if self.provider else ""

    @model.setter
    def model(self, value: str):
        if self.provider:
            self.provider.model = value

    # ---- Public high-level API ----

    async def chat(
        self,
        message: str,
        conversation_history: Optional[List[Dict]] = None,
        use_tools: bool = None,
    ) -> str:
        """Send chat message to LLM.

        Args:
            message: User message
            conversation_history: Previous conversation messages
            use_tools: Enable tool calling for this request

        Returns:
            LLM response
        """
        if not self.provider or not self.provider.is_configured():
            raise ValueError("LLM provider not configured. Please set the appropriate API key.")

        should_use_tools = (use_tools if use_tools is not None else self.enable_tools) and self._has_tools()

        messages = self._build_messages(message, conversation_history)

        try:
            if should_use_tools:
                return await self._chat_with_tools(messages)
            else:
                response, _ = await self.provider.chat_completion(messages)
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
        reasoning_effort: str = "medium",
    ) -> AsyncGenerator[str, None]:
        """Send chat message to LLM with streaming response.

        Args:
            message: User message
            conversation_history: Previous conversation messages
            use_tools: Enable tool calling for this request
            deep_thinking: Enable deep thinking mode
            reasoning_effort: Reasoning effort level

        Yields:
            Stream of text chunks
        """
        if not self.provider or not self.provider.is_configured():
            raise ValueError("LLM provider not configured. Please set the appropriate API key.")

        should_use_tools = (use_tools if use_tools is not None else self.enable_tools) and self._has_tools()

        messages = self._build_messages(message, conversation_history)

        try:
            if deep_thinking:
                thinking_started = False
                async for content, thinking in self.provider.chat_completion_stream_with_thinking(
                    messages,
                    enable_thinking=True,
                    reasoning_effort=reasoning_effort,
                ):
                    if thinking is not None:
                        if not thinking_started:
                            yield "[THINKING_START]"
                            thinking_started = True
                        yield thinking
                    elif content is not None:
                        if thinking_started:
                            yield "[THINKING_END]"
                        yield content
            else:
                async for content in self.provider.chat_completion_stream(messages):
                    yield content
        except Exception as e:
            logger.error(f"Error calling LLM stream: {e}", exc_info=True)
            raise

    # ---- Low-level API (used by executors) ----

    async def _chat_completion(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        max_continuations: int = 5,
    ) -> str:
        """Non-streaming chat completion with auto-continuation on truncation.

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
        if not self.provider or not self.provider.is_configured():
            raise ValueError("LLM provider not configured.")

        prepared = self._inject_system_prompt(messages, system_prompt)
        response, _ = await self.provider.chat_completion(
            prepared,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            max_continuations=max_continuations,
        )
        return response

    async def _chat_completion_stream(
        self,
        messages: List[Dict],
    ) -> AsyncGenerator[str, None]:
        """Stream chat completion (without thinking).

        Args:
            messages: Conversation messages

        Yields:
            Stream of text chunks
        """
        if not self.provider or not self.provider.is_configured():
            raise ValueError("LLM provider not configured.")

        async for chunk in self.provider.chat_completion_stream(messages):
            yield chunk

    async def _chat_completion_stream_with_thinking(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        enable_thinking: bool = True,
        reasoning_effort: str = "medium",
    ) -> AsyncGenerator[Tuple[Optional[str], Optional[str]], None]:
        """Stream chat completion with thinking support.

        Args:
            messages: Conversation messages
            model: Model override
            temperature: Temperature override
            max_tokens: Max tokens override
            system_prompt: Optional system prompt
            enable_thinking: Enable extended thinking
            reasoning_effort: Reasoning effort level

        Yields:
            Tuple of (content, thinking_content) — one will be non-None
        """
        if not self.provider or not self.provider.is_configured():
            raise ValueError("LLM provider not configured.")

        prepared = self._inject_system_prompt(messages, system_prompt)
        async for result in self.provider.chat_completion_stream_with_thinking(
            prepared,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            enable_thinking=enable_thinking,
            reasoning_effort=reasoning_effort,
        ):
            yield result

    async def _chat_completion_stream_with_tools(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        enable_thinking: bool = True,
        reasoning_effort: str = "medium",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream chat completion with tool_calls support.

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
        if not self.provider or not self.provider.is_configured():
            raise ValueError("LLM provider not configured.")

        prepared = self._inject_system_prompt(messages, system_prompt)
        async for event in self.provider.chat_completion_stream_with_tools(
            prepared,
            tools=tools,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            enable_thinking=enable_thinking,
            reasoning_effort=reasoning_effort,
        ):
            yield event

    # ---- Simple completion for internal use (replaces direct volc_client access) ----

    async def simple_completion(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 500,
    ) -> Optional[str]:
        """Simple non-streaming completion for internal use.

        Replaces direct volc_client access in session_working_memory,
        agent_memory_service, etc.

        Args:
            messages: Conversation messages
            model: Model override
            temperature: Temperature (default 0.3 for concise outputs)
            max_tokens: Max tokens (default 500 for summaries/extracts)

        Returns:
            Response text or None if not configured
        """
        if not self.provider or not self.provider.is_configured():
            return None

        try:
            response, _ = await self.provider.chat_completion(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                max_continuations=1,
            )
            return response
        except Exception as e:
            logger.error(f"Error in simple_completion: {e}", exc_info=True)
            return None

    # ---- Configuration ----

    def is_configured(self) -> bool:
        """Check if LLM service is properly configured."""
        return bool(self.provider) and self.provider.is_configured()

    def reconfigure(self):
        """Reconfigure LLM service with current settings values.

        Called when LLM-related settings are updated via the settings page.
        Rebuilds the provider with new API key / base URL / model.
        """
        provider_name = getattr(settings, "LLM_PROVIDER", "volcengine")
        self.provider = _create_provider(provider_name)

        if self.provider and self.provider.is_configured():
            logger.info(f"LLM service reconfigured: provider={provider_name}, model={self.provider.model}")
        else:
            logger.warning("LLM service reconfigured but provider not properly configured")

    # ---- Helpers ----

    def _has_tools(self) -> bool:
        """Check if tools are available."""
        from app.services.mcp_pool import mcp_client_pool
        return len(mcp_client_pool.local_tools) > 0

    async def _get_tools_format(
        self,
        allowed_tools: Optional[List[str]] = None,
        enabled_mcp_servers: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Get tools in OpenAI format for LLM API."""
        from app.core.tool_manager import get_tool_manager
        tool_manager = get_tool_manager()
        return await tool_manager.get_tools_for_llm(
            enabled_mcp_servers=enabled_mcp_servers,
            allowed_tools=allowed_tools,
        )

    def _build_messages(
        self,
        message: str,
        conversation_history: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        """Build message list for LLM API."""
        messages = []
        if conversation_history:
            for msg in conversation_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ["user", "assistant"]:
                    messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": message})
        return messages

    @staticmethod
    def _inject_system_prompt(
        messages: List[Dict],
        system_prompt: Optional[str] = None,
    ) -> List[Dict]:
        """Inject system prompt at the beginning of messages if provided."""
        if system_prompt is None:
            return messages
        if messages and messages[0].get("role") == "system":
            return messages
        return [{"role": "system", "content": system_prompt}] + messages

    async def _chat_with_tools(self, messages: List[Dict]) -> str:
        """Chat with tool support (placeholder — main tool flow goes through ReActCot)."""
        # TODO: Implement tool calling flow if needed outside of ReActCot
        response, _ = await self.provider.chat_completion(messages)
        return response


# Global LLM service instance
llm_service = LLMService()
