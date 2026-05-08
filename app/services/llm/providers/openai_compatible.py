"""Generic OpenAI-compatible LLM provider

Works with any API that follows the OpenAI chat completions format,
e.g. custom deployments, third-party gateways, self-hosted models, etc.
"""
import asyncio
import logging
from typing import Optional, List, Dict, Any, Tuple, AsyncGenerator

from app.services.llm.providers.base import LLMProvider

try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """Generic OpenAI-compatible provider.

    Use this for any service that exposes an OpenAI-compatible chat API,
    such as CodingPlan, OneAPI, FastGPT, LiteLLM proxy, etc.

    Thinking support: if the upstream model returns `reasoning_content`
    (like DeepSeek-reasoner), it will be yielded as thinking content.
    Otherwise, thinking is simulated by a pre-call if desired.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "",
        base_url: str = "",
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._temperature = temperature
        self._max_tokens = max_tokens

        self.client = None
        if AsyncOpenAI and self._api_key and self._base_url:
            self.client = AsyncOpenAI(
                base_url=self._base_url,
                api_key=self._api_key,
            )
            logger.info(f"OpenAI-compatible provider initialized: base_url={self._base_url}, model={self._model}")
        elif not self._base_url:
            logger.warning("OpenAI-compatible provider: LLM_BASE_URL is required")

    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str):
        self._model = value

    def is_configured(self) -> bool:
        return bool(self._api_key) and bool(self._base_url) and bool(self.client)

    async def chat_completion(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_continuations: int = 5,
    ) -> Tuple[str, str]:
        if not self.client:
            raise ValueError("OpenAI-compatible provider not configured. Set LLM_API_KEY and LLM_BASE_URL.")

        effective_model = model or self._model
        effective_max_tokens = max_tokens if max_tokens is not None else self._max_tokens

        api_params = {
            "model": effective_model,
            "messages": messages,
            "max_tokens": effective_max_tokens,
        }
        if temperature is not None:
            api_params["temperature"] = temperature

        full_response = ""
        current_messages = list(messages)

        for attempt in range(max_continuations + 1):
            api_params["messages"] = current_messages
            response = await self.client.chat.completions.create(**api_params)

            result_text = response.choices[0].message.content or ""
            finish_reason = response.choices[0].finish_reason or "stop"
            full_response += result_text

            if finish_reason != "length":
                break

            logger.warning(
                f"Response truncated (attempt {attempt + 1}), auto-continuing..."
            )
            current_messages.append({"role": "assistant", "content": result_text})
            current_messages.append(
                {"role": "user", "content": "请继续输出，从你刚才中断的地方继续，不要重复已经输出的内容："}
            )

        return full_response, finish_reason

    async def chat_completion_stream(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        if not self.client:
            raise ValueError("OpenAI-compatible provider not configured.")

        api_params = {
            "model": model or self._model,
            "messages": messages,
            "stream": True,
        }
        if temperature is not None:
            api_params["temperature"] = temperature
        if max_tokens is not None:
            api_params["max_tokens"] = max_tokens

        stream = await self.client.chat.completions.create(**api_params)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                if content:
                    yield content

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
        if not self.client:
            raise ValueError("OpenAI-compatible provider not configured.")

        effective_model = model or self._model

        prepared_messages = list(messages)
        if system_prompt is not None:
            if not prepared_messages or prepared_messages[0].get("role") != "system":
                prepared_messages = [{"role": "system", "content": system_prompt}] + prepared_messages

        api_params = {
            "model": effective_model,
            "messages": prepared_messages,
            "stream": True,
        }
        if temperature is not None:
            api_params["temperature"] = temperature
        if max_tokens is not None:
            api_params["max_tokens"] = max_tokens

        stream = await self.client.chat.completions.create(**api_params)
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # Check for reasoning_content (DeepSeek-reasoner style)
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield (None, reasoning)

            if delta.content:
                yield (delta.content, None)

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
        if not self.client:
            raise ValueError("OpenAI-compatible provider not configured.")

        effective_model = model or self._model

        prepared_messages = list(messages)
        if system_prompt is not None:
            if not prepared_messages or prepared_messages[0].get("role") != "system":
                prepared_messages = [{"role": "system", "content": system_prompt}] + prepared_messages

        api_params = {
            "model": effective_model,
            "messages": prepared_messages,
            "stream": True,
        }
        if temperature is not None:
            api_params["temperature"] = temperature
        if max_tokens is not None:
            api_params["max_tokens"] = max_tokens
        if tools:
            api_params["tools"] = tools

        stream = await self.client.chat.completions.create(**api_params)

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # Check for reasoning_content
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield {"type": "thinking", "content": reasoning}

            if delta.content:
                yield {"type": "content", "content": delta.content}

            # Yield incremental tool_call deltas (executor handles accumulation)
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                tool_calls_list = []
                for tc in delta.tool_calls:
                    tool_calls_list.append({
                        "index": tc.index,
                        "id": tc.id or "",
                        "type": tc.type or "function",
                        "function": {
                            "name": tc.function.name if tc.function else "",
                            "arguments": tc.function.arguments if tc.function else "",
                        },
                    })
                if tool_calls_list:
                    yield {"type": "tool_calls", "tool_calls": tool_calls_list}

        yield {"type": "done"}

    def reconfigure(self, **kwargs):
        """Reconfigure the provider with new settings."""
        self._api_key = kwargs.get("api_key", self._api_key)
        self._model = kwargs.get("model", self._model)
        self._base_url = kwargs.get("base_url", self._base_url)
        self._temperature = kwargs.get("temperature", self._temperature)
        self._max_tokens = kwargs.get("max_tokens", self._max_tokens)

        if AsyncOpenAI and self._api_key and self._base_url:
            self.client = AsyncOpenAI(
                base_url=self._base_url,
                api_key=self._api_key,
            )
            logger.info(f"OpenAI-compatible provider reconfigured: base_url={self._base_url}, model={self._model}")
        else:
            self.client = None
            logger.warning("OpenAI-compatible provider reconfigured but missing API key or base URL")
