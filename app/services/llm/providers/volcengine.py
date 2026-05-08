"""Volcengine LLM provider using the Ark SDK with deep thinking support"""
import asyncio
import logging
import threading
from queue import Queue
from typing import Optional, List, Dict, Any, Tuple, AsyncGenerator

from app.services.llm.providers.base import LLMProvider

try:
    from volcenginesdkarkruntime import Ark
except ImportError:
    Ark = None

logger = logging.getLogger(__name__)


class VolcengineProvider(LLMProvider):
    """Volcengine LLM provider using the Ark SDK."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._temperature = temperature
        self._max_tokens = max_tokens

        self.client = None
        if Ark and self._api_key:
            self.client = Ark(base_url=self._base_url, api_key=self._api_key)
            logger.info(f"Volcengine provider initialized with model: {self._model}")

    @property
    def provider_name(self) -> str:
        return "volcengine"

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str):
        self._model = value

    def is_configured(self) -> bool:
        return bool(self._api_key) and bool(self.client)

    async def chat_completion(
        self,
        messages: List[Dict],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        max_continuations: int = 5,
    ) -> Tuple[str, str]:
        if not self.client:
            raise ValueError("Volcengine client not configured. Please set LLM_API_KEY.")

        effective_max_tokens = max_tokens if max_tokens is not None else self._max_tokens
        logger.info(
            f"Volcengine chat_completion: model={model or self._model}, "
            f"messages={len(messages)}, max_tokens={effective_max_tokens}"
        )

        api_params = {
            "model": model or self._model,
            "messages": messages,
            "stream": False,
            "max_tokens": effective_max_tokens,
        }
        if temperature is not None:
            api_params["temperature"] = temperature

        loop = asyncio.get_event_loop()
        full_response = ""
        current_messages = list(messages)

        for attempt in range(max_continuations + 1):
            api_params["messages"] = current_messages
            result_text, finish_reason = await loop.run_in_executor(
                None, self._sync_call_with_finish_reason, api_params
            )

            full_response += result_text
            logger.info(
                f"Volcengine attempt {attempt + 1}: received {len(result_text)} chars, "
                f"finish_reason={finish_reason}"
            )

            if finish_reason != "length":
                break

            logger.warning(
                f"Volcengine response truncated (attempt {attempt + 1}), "
                f"auto-continuing... (total so far: {len(full_response)} chars)"
            )
            current_messages.append({"role": "assistant", "content": result_text})
            current_messages.append(
                {"role": "user", "content": "请继续输出，从你刚才中断的地方继续，不要重复已经输出的内容："}
            )

        logger.info(
            f"Volcengine chat_completion complete, total {len(full_response)} characters "
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
            raise ValueError("Volcengine client not configured. Please set LLM_API_KEY.")

        chunk_queue = Queue()
        error_queue = Queue()

        def run_sync_stream():
            try:
                completion = self.client.chat.completions.create(
                    model=model or self._model,
                    messages=messages,
                    stream=True,
                )
                with completion:
                    for chunk in completion:
                        if chunk.choices and chunk.choices[0].delta.content:
                            content = chunk.choices[0].delta.content
                            if content:
                                chunk_queue.put(content)
                chunk_queue.put(None)  # Sentinel
            except Exception as e:
                logger.error(f"Error in Volcengine sync stream: {e}", exc_info=True)
                error_queue.put(str(e))

        thread = threading.Thread(target=run_sync_stream, daemon=True)
        thread.start()

        loop = asyncio.get_event_loop()
        try:
            while True:
                try:
                    content = await loop.run_in_executor(None, chunk_queue.get, True, 0.1)
                except Exception:
                    if not thread.is_alive():
                        if not error_queue.empty():
                            error_msg = error_queue.get()
                            raise Exception(f"Stream error: {error_msg}")
                        try:
                            content = chunk_queue.get_nowait()
                        except Exception:
                            break
                    continue

                if content is None:
                    break
                yield content
        finally:
            if thread.is_alive():
                thread.join(timeout=1.0)

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
            raise ValueError("Volcengine client not configured. Please set LLM_API_KEY.")

        chunk_queue = Queue()
        error_queue = Queue()

        def run_sync_stream():
            try:
                api_params = {
                    "model": model or self._model,
                    "messages": messages,
                    "stream": True,
                }
                if temperature is not None:
                    api_params["temperature"] = temperature
                if max_tokens is not None:
                    api_params["max_tokens"] = max_tokens
                if system_prompt is not None:
                    api_params["messages"] = [{"role": "system", "content": system_prompt}] + messages

                if enable_thinking:
                    api_params["thinking"] = {"type": "enabled"}
                    api_params["reasoning_effort"] = reasoning_effort
                else:
                    api_params["thinking"] = {"type": "disabled"}

                logger.info(
                    f"Volcengine streaming with thinking: model={api_params['model']}, "
                    f"enable_thinking={enable_thinking}"
                )

                completion = self.client.chat.completions.create(**api_params)
                with completion:
                    for chunk in completion:
                        if chunk.choices and chunk.choices[0].delta.reasoning_content:
                            content = chunk.choices[0].delta.reasoning_content
                            if content:
                                chunk_queue.put(("thinking", content))
                        if chunk.choices and chunk.choices[0].delta.content:
                            content = chunk.choices[0].delta.content
                            if content:
                                chunk_queue.put(("content", content))

                chunk_queue.put(("end", None))

            except Exception as e:
                logger.error(f"Error in Volcengine thinking stream: {e}", exc_info=True)
                error_queue.put(str(e))

        thread = threading.Thread(target=run_sync_stream, daemon=True)
        thread.start()

        loop = asyncio.get_event_loop()
        try:
            while True:
                try:
                    chunk = await loop.run_in_executor(None, chunk_queue.get, True, 0.1)
                except Exception:
                    if not thread.is_alive():
                        if not error_queue.empty():
                            error_msg = error_queue.get()
                            raise Exception(f"Stream error: {error_msg}")
                        try:
                            chunk = chunk_queue.get_nowait()
                        except Exception:
                            break
                    else:
                        continue

                chunk_type, value = chunk
                if chunk_type == "end":
                    break
                if chunk_type == "thinking":
                    yield (None, value)
                elif chunk_type == "content":
                    yield (value, None)
        finally:
            if thread.is_alive():
                thread.join(timeout=1.0)

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
            raise ValueError("Volcengine client not configured. Please set LLM_API_KEY.")

        chunk_queue = Queue()
        error_queue = Queue()

        def run_sync_stream():
            try:
                api_params = {
                    "model": model or self._model,
                    "messages": messages,
                    "stream": True,
                }
                if temperature is not None:
                    api_params["temperature"] = temperature
                if max_tokens is not None:
                    api_params["max_tokens"] = max_tokens
                if tools:
                    api_params["tools"] = tools
                if system_prompt is not None:
                    if not messages or messages[0].get("role") != "system":
                        api_params["messages"] = [{"role": "system", "content": system_prompt}] + messages

                if enable_thinking:
                    api_params["thinking"] = {"type": "enabled"}
                    api_params["reasoning_effort"] = reasoning_effort
                else:
                    api_params["thinking"] = {"type": "disabled"}

                logger.info(
                    f"Volcengine streaming with tools: model={api_params['model']}, "
                    f"tools={len(tools) if tools else 0}"
                )

                completion = self.client.chat.completions.create(**api_params)
                with completion:
                    for chunk in completion:
                        if chunk.choices and chunk.choices[0].delta.reasoning_content:
                            content = chunk.choices[0].delta.reasoning_content
                            if content:
                                chunk_queue.put({"type": "thinking", "content": content})

                        if chunk.choices and chunk.choices[0].delta.content:
                            content = chunk.choices[0].delta.content
                            if content:
                                chunk_queue.put({"type": "content", "content": content})

                        if chunk.choices and chunk.choices[0].delta.tool_calls:
                            tool_calls = chunk.choices[0].delta.tool_calls
                            if tool_calls:
                                tool_calls_list = []
                                for tc in tool_calls:
                                    tc_dict = {
                                        "index": tc.index,
                                        "id": tc.id,
                                        "type": tc.type,
                                        "function": {
                                            "name": tc.function.name,
                                            "arguments": tc.function.arguments,
                                        },
                                    }
                                    tool_calls_list.append(tc_dict)
                                chunk_queue.put({"type": "tool_calls", "tool_calls": tool_calls_list})

                chunk_queue.put({"type": "done"})

            except Exception as e:
                logger.error(f"Error in Volcengine tools stream: {e}", exc_info=True)
                error_queue.put(str(e))

        thread = threading.Thread(target=run_sync_stream, daemon=True)
        thread.start()

        loop = asyncio.get_event_loop()
        try:
            while True:
                try:
                    chunk = await loop.run_in_executor(None, chunk_queue.get, True, 0.1)
                except Exception:
                    if not thread.is_alive():
                        if not error_queue.empty():
                            error_msg = error_queue.get()
                            raise Exception(f"Stream error: {error_msg}")
                        try:
                            chunk = chunk_queue.get_nowait()
                        except Exception:
                            break
                    else:
                        continue

                yield chunk
                if chunk["type"] == "done":
                    break
        finally:
            if thread.is_alive():
                thread.join(timeout=1.0)

    def _sync_call_with_finish_reason(self, api_params: Dict) -> Tuple[str, str]:
        """Synchronous API call, returns (text, finish_reason)."""
        completion = self.client.chat.completions.create(**api_params)
        if completion.choices and completion.choices[0].message.content:
            finish_reason = completion.choices[0].finish_reason or "stop"
            if finish_reason == "length":
                logger.warning(
                    f"Volcengine response truncated (finish_reason=length), "
                    f"max_tokens={api_params.get('max_tokens')}"
                )
            return completion.choices[0].message.content, finish_reason
        return "", "stop"

    def reconfigure(self, **kwargs):
        """Reconfigure the provider with new settings."""
        self._api_key = kwargs.get("api_key", self._api_key)
        self._model = kwargs.get("model", self._model)
        self._base_url = kwargs.get("base_url", self._base_url)
        self._temperature = kwargs.get("temperature", self._temperature)
        self._max_tokens = kwargs.get("max_tokens", self._max_tokens)

        if Ark and self._api_key:
            self.client = Ark(base_url=self._base_url, api_key=self._api_key)
            logger.info(f"Volcengine provider reconfigured with model: {self._model}")
        else:
            self.client = None
            logger.warning("Volcengine provider reconfigured but no API key available")
