"""
示例 Skill 脚本

演示如何实现 Skill 的 execute 函数
"""
from typing import Any, Dict
from datetime import datetime

# 注意：我们不需要在这里导入 SkillExecutionContext，
# 因为它会在调用时传入


def execute(context) -> Dict[str, Any]:
    """
    Skill 入口函数

    Args:
        context: 执行上下文，包含：
            - input_data: 输入数据
            - config: 配置
            - state: 状态（可修改）

    Returns:
        输出结果
    """
    input_data = context.input_data or {}
    state = context.state

    # 更新访问计数
    visit_count = state.get("visit_count", 0) + 1
    state["visit_count"] = visit_count
    state["last_visit"] = datetime.utcnow().isoformat()

    # 处理输入
    name = input_data.get("name", "Guest")
    a = input_data.get("a", 0)
    b = input_data.get("b", 0)

    # 生成结果
    result = {
        "greeting": f"Hello, {name}!",
        "sum": a + b,
        "product": a * b,
        "visit_count": visit_count,
        "skill": "example_script",
    }

    return result
