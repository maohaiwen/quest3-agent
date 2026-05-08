"""DeepSeek LLM provider using the OpenAI-compatible API with thinking + tool support

DeepSeek API docs:
- Thinking mode: extra_body={"thinking": {"type": "enabled"}} + reasoning_effort
- Thinking + tools work together (v4 models)
- Thinking mode does NOT support temperature/top_p/etc
- reasoning_content must be preserved in multi-turn + tool-call context
- effort mapping: low/medium → high, xhigh → max
"""
import json
import logging
from typing import Optional, List, Dict, Any, Tuple, AsyncGenerator

from app.services.llm.providers.base import LLMProvider

try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

logger = logging.getLogger(__name__)


def _map_reasoning_effort(effort: str) -> str:
    """Map effort levels to DeepSeek's supported values.

    DeepSeek only supports 'high' and 'max'.
    low/medium map to high, xhigh maps to max.
    """
    effort = effort.lower()
    if effort in ("low", "medium", "high"):
        return "high"
    if effort in ("xhigh", "max"):
        return "max"
    return "high"


class DeepSeekProvider(LLMProvider):
    """DeepSeek LLM provider.

    Uses the openai AsyncOpenAI SDK for native async support.
    Supports thinking mode (with reasoning_content) and tool_calls together.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com/v1",
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._temperature = temperature
        self._max_tokens = max_tokens

        self.client = None
        if AsyncOpenAI and self._api_key:
            self.client = AsyncOpenAI(
                base_url=self._base_url,
                api_key=self._api_key,
            )
            logger.info(f"DeepSeek provider initialized with model: {self._model}")

    @property
    def provider_name(self) -> str:
        return "deepseek"

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str):
        self._model = value

    def is_configured(self) -> bool:
        return bool(self._api_key) and bool(self.client)

    def _is_thinking_model(self, model: Optional[str] = None) -> bool:
        """Check if the model supports thinking mode.

        DeepSeek v4 models (deepseek-v4-pro, deepseek-v4-flash) and
        deepseek-reasoner support thinking mode.
        """
        m = (model or self._model).lower()
        # v4 models and reasoner support thinking
        return "v4" in m or "reasoner" in m

    def _build_api_params(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        tools: Optional[List[Dict]] = None,
        enable_thinking: bool = False,
        reasoning_effort: str = "medium",
    ) -> Dict[str, Any]:
        """Build common API parameters.

        Centralizes all DeepSeek-specific parameter handling:
        - thinking mode via extra_body
        - reasoning_effort mapping
        - no temperature in thinking mode
        """
        effective_model = model or self._model

        params: Dict[str, Any] = {
            "model": effective_model,
            "messages": messages,
        }

        if stream:
            params["stream"] = True

        if max_tokens is not None:
            params["max_tokens"] = max_tokens

        # Thinking mode
        if enable_thinking:
            params["extra_body"] = {"thinking": {"type": "enabled"}}
            params["reasoning_effort"] = _map_reasoning_effort(reasoning_effort)
            # Thinking mode does NOT support temperature — omit it
        else:
            # Non-thinking mode: temperature is allowed
            if temperature is not None:
                params["temperature"] = temperature

        if tools:
            params["tools"] = tools

        return params

    async def chat_completion(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_continuations: int = 5,
    ) -> Tuple[str, str]:
        if not self.client:
            raise ValueError("DeepSeek client not configured. Please set LLM_API_KEY.")

        effective_max_tokens = max_tokens if max_tokens is not None else self._max_tokens
        logger.info(
            f"DeepSeek chat_completion: model={model or self._model}, "
            f"messages={len(messages)}, max_tokens={effective_max_tokens}"
        )

        full_response = ""
        current_messages = list(messages)

        for attempt in range(max_continuations + 1):
            api_params = self._build_api_params(
                messages=current_messages,
                model=model,
                temperature=temperature,
                max_tokens=effective_max_tokens,
                stream=False,
            )
            response = await self.client.chat.completions.create(**api_params)

            result_text = response.choices[0].message.content or ""
            finish_reason = response.choices[0].finish_reason or "stop"
            full_response += result_text

            logger.info(
                f"DeepSeek attempt {attempt + 1}: received {len(result_text)} chars, "
                f"finish_reason={finish_reason}"
            )

            if finish_reason != "length":
                break

            logger.warning(
                f"DeepSeek response truncated (attempt {attempt + 1}), "
                f"auto-continuing... (total so far: {len(full_response)} chars)"
            )
            current_messages.append({"role": "assistant", "content": result_text})
            current_messages.append(
                {"role": "user", "content": "请继续输出，从你刚才中断的地方继续，不要重复已经输出的内容："}
            )

        logger.info(
            f"DeepSeek chat_completion complete, total {len(full_response)} characters "
            f"after {attempt + 1} attempt(s)"
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
            raise ValueError("DeepSeek client not configured. Please set LLM_API_KEY.")

        api_params = self._build_api_params(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

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
            raise ValueError("DeepSeek client not configured. Please set LLM_API_KEY.")

        prepared_messages = list(messages)
        if system_prompt is not None:
            if not prepared_messages or prepared_messages[0].get("role") != "system":
                prepared_messages = [{"role": "system", "content": system_prompt}] + prepared_messages

        api_params = self._build_api_params(
            messages=prepared_messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            enable_thinking=enable_thinking,
            reasoning_effort=reasoning_effort,
        )

        effective_model = api_params["model"]
        logger.info(
            f"DeepSeek streaming with thinking: model={effective_model}, "
            f"enable_thinking={enable_thinking}, effort={reasoning_effort}"
        )

        stream = await self.client.chat.completions.create(**api_params)
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # DeepSeek returns reasoning_content for thinking
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
        """Stream with thinking + tool_calls support.

        DeepSeek supports thinking and tools together. When both are enabled:
        - reasoning_content is returned alongside content and tool_calls
        - The assistant message with tool_calls MUST include reasoning_content
          in subsequent requests
        """
        if not self.client:
            raise ValueError("DeepSeek client not configured. Please set LLM_API_KEY.")

        prepared_messages = list(messages)
        if system_prompt is not None:
            if not prepared_messages or prepared_messages[0].get("role") != "system":
                prepared_messages = [{"role": "system", "content": system_prompt}] + prepared_messages

        api_params = self._build_api_params(
            messages=prepared_messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            tools=tools,
            enable_thinking=enable_thinking,
            reasoning_effort=reasoning_effort,
        )

        effective_model = api_params["model"]
        logger.info(
            f"DeepSeek streaming with tools: model={effective_model}, "
            f"tools={len(tools) if tools else 0}, "
            f"thinking={enable_thinking}, effort={reasoning_effort}"
        )

        stream = await self.client.chat.completions.create(**api_params)

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # Yield thinking content
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield {"type": "thinking", "content": reasoning}

            # Yield regular content
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

        if AsyncOpenAI and self._api_key:
            self.client = AsyncOpenAI(
                base_url=self._base_url,
                api_key=self._api_key,
            )
            logger.info(f"DeepSeek provider reconfigured with model: {self._model}")
        else:
            self.client = None
            logger.warning("DeepSeek provider reconfigured but no API key available")
