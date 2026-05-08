"""思维链管理器 - 通过 LLMService 统一接口实现思维链功能"""
import logging
from typing import Optional, Dict, List, Any, AsyncGenerator

logger = logging.getLogger(__name__)


class ThinkingChainManager:
    """
    思维链管理器
    负责统一管理思维链的生成、解析和流式输出
    通过 LLMService 的统一接口调用，不再直接依赖特定 SDK
    """

    def __init__(self):
        """初始化思维链管理器"""
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
            from app.services.llm_service import llm_service

            if not llm_service.is_configured():
                yield {"type": "error", "message": "LLM not configured"}
                return

            model = kwargs.get("model")

            has_thinking = False
            has_content = False

            async for content, thinking in llm_service._chat_completion_stream_with_thinking(
                messages,
                model=model,
                enable_thinking=thinking_enabled,
                reasoning_effort=reasoning,
            ):
                if thinking is not None:
                    if not has_thinking:
                        yield {
                            "type": "thinking_start",
                            "message": "开始思考..."
                        }
                        has_thinking = True
                    yield {
                        "type": "thinking",
                        "content": thinking
                    }
                elif content is not None:
                    if has_thinking and not has_content:
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


def get_thinking_manager() -> ThinkingChainManager:
    """获取或创建思维链管理器全局实例"""
    global _thinking_manager_instance
    if _thinking_manager_instance is None:
        _thinking_manager_instance = ThinkingChainManager()
    return _thinking_manager_instance
