"""LLM Provider abstract base class"""
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Tuple, AsyncGenerator


class LLMProvider(ABC):
    """LLM provider abstract base class.

    Each provider implements this interface to support a specific LLM API
    (Volcengine, DeepSeek, OpenAI, etc.). The LLMService facade delegates
    all calls to the currently configured provider.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider identifier (e.g. 'volcengine', 'deepseek')."""
        ...

    @property
    @abstractmethod
    def model(self) -> str:
        """Return the default model name for this provider."""
        ...

    @model.setter
    @abstractmethod
    def model(self, value: str):
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if the provider is properly configured (has API key, client, etc.)."""
        ...

    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_continuations: int = 5,
    ) -> Tuple[str, str]:
        """Non-streaming chat completion with auto-continuation on truncation.

        Args:
            messages: Conversation messages
            model: Model override
            temperature: Temperature override
            max_tokens: Max tokens override
            max_continuations: Max auto-continuation attempts when truncated

        Returns:
            Tuple of (response_text, finish_reason)
        """
        ...

    @abstractmethod
    async def chat_completion_stream(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming chat completion without thinking.

        Args:
            messages: Conversation messages
            model: Model override
            temperature: Temperature override
            max_tokens: Max tokens override

        Yields:
            Text chunks
        """
        ...

    @abstractmethod
    async def chat_completion_stream_with_thinking(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        enable_thinking: bool = True,
        reasoning_effort: str = "medium",
    ) -> AsyncGenerator[Tuple[Optional[str], Optional[str]], None]:
        """Streaming chat completion with thinking support.

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
        ...

    @abstractmethod
    async def chat_completion_stream_with_tools(
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
        """Streaming chat completion with tool_calls support.

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
            Event dicts with type: "thinking", "content", "tool_calls", or "done"
        """
        ...

    @abstractmethod
    def reconfigure(self, **kwargs):
        """Reconfigure the provider with new settings."""
        ...
