"""推理深度策略 - 管理 reasoning_effort 参数配置"""
import logging
from typing import Dict, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class ReasoningEffort(Enum):
    """推理深度枚举"""
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReasoningEffortStrategy:
    """
    推理深度策略管理器
    负责管理不同推理深度级别的配置
    """

    # 默认配置
    DEFAULT_CONFIGS: Dict[str, Dict[str, Any]] = {
        "minimal": {
            "reasoning_effort": "minimal",
            "max_tokens": 4096,
            "temperature": 0.1,
            "description": "最小推理深度，快速响应，适合简单任务"
        },
        "low": {
            "reasoning_effort": "low",
            "max_tokens": 8192,
            "temperature": 0.3,
            "description": "低推理深度，平衡速度与质量"
        },
        "medium": {
            "reasoning_effort": "medium",
            "max_tokens": 16384,
            "temperature": 0.5,
            "description": "中等推理深度，适合复杂问题"
        },
        "high": {
            "reasoning_effort": "high",
            "max_tokens": 32768,
            "temperature": 0.7,
            "description": "高推理深度，深度思考，适合复杂规划任务"
        }
    }

    def __init__(self, default_effort: str = "medium"):
        """
        初始化推理深度策略管理器

        Args:
            default_effort: 默认推理深度
        """
        self.default_effort = self._validate_effort(default_effort)
        logger.info(f"ReasoningEffortStrategy initialized with default effort: {self.default_effort}")

    def get_config(self, effort: Optional[str] = None) -> Dict[str, Any]:
        """
        获取指定推理深度的配置

        Args:
            effort: 推理深度 (minimal/low/medium/high)

        Returns:
            配置字典
        """
        if effort is None:
            effort = self.default_effort

        effort = self._validate_effort(effort)
        return self.DEFAULT_CONFIGS.get(effort, self.DEFAULT_CONFIGS["medium"]).copy()

    def validate_and_normalize(self, effort: Any) -> str:
        """
        验证并规范化推理深度参数

        Args:
            effort: 输入的推理深度值

        Returns:
            规范化后的推理深度字符串
        """
        if effort is None:
            return self.default_effort

        return self._validate_effort(str(effort))

    def _validate_effort(self, effort: str) -> str:
        """
        验证推理深度参数

        Args:
            effort: 推理深度字符串

        Returns:
            有效的推理深度

        Raises:
            ValueError: 如果推理深度无效
        """
        effort_lower = effort.lower()

        if effort_lower not in self.DEFAULT_CONFIGS:
            logger.warning(f"Invalid reasoning_effort '{effort}', using default '{self.default_effort}'")
            return self.default_effort

        return effort_lower

    def get_all_levels(self) -> Dict[str, str]:
        """
        获取所有可用的推理深度级别及其描述

        Returns:
            字典：{级别: 描述}
        """
        return {
            level: config["description"]
            for level, config in self.DEFAULT_CONFIGS.items()
        }

    def update_config(self, effort: str, config: Dict[str, Any]):
        """
        更新指定推理深度的配置

        Args:
            effort: 推理深度
            config: 新配置
        """
        effort = self._validate_effort(effort)
        self.DEFAULT_CONFIGS[effort].update(config)
        logger.info(f"Updated config for reasoning_effort '{effort}': {config}")


# 全局实例
_reasoning_strategy_instance: Optional[ReasoningEffortStrategy] = None


def get_reasoning_strategy(default_effort: str = "medium") -> ReasoningEffortStrategy:
    """获取推理深度策略管理器全局实例"""
    global _reasoning_strategy_instance
    if _reasoning_strategy_instance is None:
        _reasoning_strategy_instance = ReasoningEffortStrategy(default_effort)
    return _reasoning_strategy_instance
