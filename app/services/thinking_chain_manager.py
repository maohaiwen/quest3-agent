"""思维链管理器 - 使用火山方舟 SDK 实现思维链功能"""
import asyncio
import logging
from typing import Optional, Dict, List, Any, AsyncGenerator

try:
    from volcenginesdkarkruntime import Ark
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("volcengine-python-sdk not installed. Run: pip install volcengine-python-sdk[ark]")
    Ark = None

logger = logging.getLogger(__name__)


class ThinkingChainManager:
    """
    思维链管理器
    负责统一管理思维链的生成、解析和流式输出
    """

    def __init__(self, client=None, base_url: str = None, api_key: str = None):
        """
        初始化思维链管理器

        Args:
            client: Ark 客户端（可选）
            base_url: API 基础 URL
            api_key: API Key
        """
        if client:
            self.client = client
        else:
            from app.config import settings
            self.client = Ark(
                base_url=base_url or getattr(settings, 'VOLCENGINE_BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3'),
                api_key=api_key
            )

        self.current_thinking_buffer = ""

    async def execute_with_thinking(
        self,
        messages: List[Dict],
        thinking_enabled: bool = True,
        reasoning: str = "medium",
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        使用思维链执行任务

        Args:
            messages: 对话消息列表
            thinking_enabled: 是否启用深度思考
            reasoning: 思考深度
            **kwargs: 其他 LLM 参数

        Yields:
            事件字典，包含：
            - {"type": "thinking_start"}: 思维开始
            - {"type": "thinking", "content": str}: 思维内容块
            - {"type": "thinking_end"}: 思维结束
            - {"type": "message", "content": str}: 回答内容块
            - {"type": "end"}: 执行结束
        """
        logger.info(f"Thinking chain execute: thinking_enabled={thinking_enabled}, reasoning_effort={reasoning}")

        try:
            from app.config import settings

            # 构建 API 参数
            api_params = {
                "model": kwargs.get("model", getattr(settings, 'VOLCENGINE_MODEL', 'DeepSeek-V3.2')),
                "messages": messages,
                "stream": True,  # 使用流式输出
            }

            # 添加 thinking 参数
            if thinking_enabled:
                api_params["thinking"] = {"type": "enabled"}
                api_params["reasoning_effort"] = reasoning
            else:
                api_params["thinking"] = {"type": "disabled"}

            # 执行流式调用 - Volcengine SDK 使用同步迭代器
            # 在线程池中运行同步代码
            def run_sync_stream():
                completion = self.client.chat.completions.create(**api_params)
                chunks = []
                with completion:
                    for chunk in completion:
                        chunks.append(chunk)
                return chunks

            # 在异步上下文中运行同步代码
            loop = asyncio.get_event_loop()
            chunks = await loop.run_in_executor(None, run_sync_stream)

            has_thinking = False
            has_content = False

            for chunk in chunks:
                # 处理思维链内容 (reasoning_content)
                if chunk.choices and chunk.choices[0].delta.reasoning_content:
                    content = chunk.choices[0].delta.reasoning_content
                    if content:
                        if not has_thinking:
                            # 第一次收到思考内容，发送 thinking_start
                            yield {
                                "type": "thinking_start",
                                "message": "开始思考..."
                            }
                            has_thinking = True

                        yield {
                            "type": "thinking",
                            "content": content
                        }

                # 处理回答内容 (content)
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    if content:
                        if has_thinking and not has_content:
                            # 第一次收到回答内容，如果之前有思考，发送 thinking_end
                            yield {
                                "type": "thinking_end",
                                "message": "思考完成"
                            }

                        has_content = True
                        yield {
                            "type": "message",
                            "content": content
                        }

            # 如果只有思考没有回答，发送 thinking_end
            if has_thinking and not has_content:
                yield {
                    "type": "thinking_end",
                    "message": "思考完成"
                }

            # 发送结束事件
            yield {"type": "end"}

        except Exception as e:
            logger.error(f"Error in thinking chain execution: {e}", exc_info=True)
            yield {
                "type": "error",
                "message": f"Thinking chain error: {str(e)}"
            }


# 全局实例（延迟初始化）
_thinking_manager_instance = None


def get_thinking_manager(client=None, base_url=None, api_key=None) -> ThinkingChainManager:
    """获取或创建思维链管理器全局实例"""
    global _thinking_manager_instance
    if _thinking_manager_instance is None:
        _thinking_manager_instance = ThinkingChainManager(client, base_url, api_key)
    return _thinking_manager_instance
