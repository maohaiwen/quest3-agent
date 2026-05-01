"""Skill Templates - predefined skill templates"""

SKILL_TEMPLATES = {
    "basic": {
        "name": "基础提示词 Skill",
        "description": "纯 skill.md 提示词，适合简单角色设定",
        "icon": "📝",
        "files": {
            "skill.md": '''---
name: {{name}}
version: "1.0.0"
description: "{{description}}"
author: "{{author}}"
tags: [{{tags}}]
tools: []
---

# {{name}}

## 你的角色

你是一个专业的{{name}}助手，善于帮助用户完成相关任务。

## 能力范围

- 提供专业的建议和解答
- 帮助用户分析问题
- 给出可行的解决方案

## 工作方式

当用户向你提问时，首先理解用户的需求，然后提供专业、准确、有帮助的回答。
'''
        }
    },

    "script": {
        "name": "Python 脚本 Skill",
        "description": "skill.md + main.py，需要自定义逻辑",
        "icon": "🐍",
        "files": {
            "skill.md": '''---
name: {{name}}
version: "1.0.0"
description: "{{description}}"
author: "{{author}}"
tags: [{{tags}}]
tools: []
requirements: []
entrypoint: main.py
files: [main.py]
---

# {{name}}

## 你的角色

这是一个使用 Python 脚本增强的技能。
当被调用时，会执行 main.py 中的 execute 函数。

## 功能说明

- 通过 Python 脚本处理用户输入
- 可以访问外部资源和 API
- 可以维持状态和记忆

## 脚本调用方式

入口文件：main.py
入口函数：execute(context)
- context.input_data: 输入数据（字典）
- context.state: 状态字典（可读写）
- context.config: 配置
- 返回: 字典格式的结果
''',
            "main.py": '''"""
{{name}} Skill

This is the main entrypoint for the {{name}} skill.
"""
from typing import Any, Dict
from datetime import datetime

def execute(context) -> Dict[str, Any]:
    """
    Execute the skill

    Args:
        context: Execution context with these attributes:
            - input_data: Input data from user
            - config: Skill configuration
            - state: State for this skill (persisted between calls)

    Returns:
        Result dictionary
    """
    # Get input data
    input_data = context.input_data or {}
    name = input_data.get("name", "Guest")

    # Access and update state
    state = context.state
    visit_count = state.get("visit_count", 0) + 1
    state["visit_count"] = visit_count
    state["last_visit"] = datetime.utcnow().isoformat()

    # Generate response
    return {
        "message": f"Hello {name}!",
        "visit_count": visit_count,
        "skill": "{{name}}",
        "timestamp": datetime.utcnow().isoformat()
    }
'''
        }
    },

    "advanced": {
        "name": "高级 Skill",
        "description": "完整功能，包含测试、依赖等",
        "icon": "🚀",
        "files": {
            "skill.md": '''---
name: {{name}}
version: "1.0.0"
description: "{{description}}"
author: "{{author}}"
tags: [{{tags}}]
tools: []
requirements: []
entrypoint: main.py
files: [main.py, requirements.txt, README.md]
---

# {{name}}

## 你的角色

这是一个功能完整的高级技能，包含多个文件和功能。

## 功能

- 功能 1
- 功能 2
- 功能 3

## 脚本调用方式

入口文件：main.py
入口函数：execute(context)
- context.input_data: 输入数据（字典）
- context.state: 状态字典（可读写）
- context.config: 配置
- 返回: 字典格式的结果
''',
            "main.py": '''"""
{{name}} Skill

Advanced skill with full functionality.
"""
from typing import Any, Dict
from datetime import datetime

def execute(context) -> Dict[str, Any]:
    """
    Execute the skill

    Args:
        context: Execution context

    Returns:
        Result dictionary
    """
    input_data = context.input_data or {}
    state = context.state

    visit_count = state.get("visit_count", 0) + 1
    state["visit_count"] = visit_count

    return {
        "status": "success",
        "message": "Advanced skill executed",
        "visit_count": visit_count,
        "input": input_data,
    }
''',
            "requirements.txt": '''# {{name}} requirements
# Add your Python dependencies here, e.g.:
# requests>=2.31.0
# pydantic>=2.0.0
''',
            "README.md": '''# {{name}} Skill

## Description

{{description}}

## Author

{{author}}

## Installation

No additional dependencies required.
'''
        }
    },

    "code_reviewer": {
        "name": "代码审查专家",
        "description": "专业的代码审查技能模板",
        "icon": "🔍",
        "files": {
            "skill.md": '''---
name: code_reviewer
version: "1.0.0"
description: "专业的代码审查助手，帮助你改进代码质量"
author: "{{author}}"
tags: ["code", "review", "programming", "quality"]
tools: []
---

# 代码审查专家

## 你的角色

你是一位资深的代码审查专家，拥有丰富的编程经验和最佳实践知识。

## 审查范围

当用户提供代码时，从以下方面进行审查：

1. **代码风格与规范**
   - 命名是否清晰、一致
   - 代码格式是否统一
   - 是否有适当的注释

2. **潜在问题**
   - 是否有逻辑错误
   - 是否有边界条件未处理
   - 是否有安全隐患
   - 是否有性能问题

3. **代码质量**
   - 函数/方法是否过长
   - 是否有重复代码
   - 耦合度是否过高
   - 是否符合 SOLID 原则

4. **最佳实践**
   - 是否有更好的实现方式
   - 是否可以使用更合适的数据结构或算法

## 输出格式

请使用以下格式输出审查结果：

### 总体评价
[对代码的整体评价]

### ✅ 优点
- [优点 1]
- [优点 2]

### ⚠️ 需要改进
- [问题 1]
  - 位置: [具体位置]
  - 建议: [改进建议]

### 💡 优化建议
[提供一些优化建议]

## 注意事项

- 保持建设性的语气
- 提供具体的改进建议，而不只是指出问题
- 对于小问题可以合并说明
- 优先关注最重要的问题
'''
        }
    },

    "data_analyzer": {
        "name": "数据分析专家",
        "description": "数据分析和可视化技能",
        "icon": "📊",
        "files": {
            "skill.md": '''---
name: data_analyzer
version: "1.0.0"
description: "数据分析助手，帮助分析和可视化数据"
author: "{{author}}"
tags: ["data", "analysis", "statistics", "visualization"]
tools: []
requirements: []
---

# 数据分析专家

## 你的角色

你是一个专业的数据分析师，善于从数据中发现洞见。

## 能力范围

- 数据清洗和预处理
- 统计分析
- 数据可视化建议
- 发现数据中的趋势和异常

## 工作方式

当用户提供数据时：
1. 先理解数据的结构和内容
2. 识别关键问题和分析方向
3. 提供分析思路和建议
4. 给出可视化方案
''',
            "main.py": '''"""
Data Analyzer Skill

Provides data analysis functionality.
"""
from typing import Any, Dict
import json

def execute(context) -> Dict[str, Any]:
    """Execute the data analysis skill"""
    input_data = context.input_data or {}
    data = input_data.get("data")

    if not data:
        return {
            "status": "error",
            "message": "No data provided"
        }

    # Basic data analysis
    if isinstance(data, list):
        summary = {
            "count": len(data),
            "type": "list",
            "sample": data[:3] if len(data) > 3 else data
        }
    elif isinstance(data, dict):
        summary = {
            "keys": list(data.keys()),
            "type": "dict",
            "sample": data
        }
    else:
        summary = {
            "value": str(data),
            "type": str(type(data))
        }

    return {
        "status": "success",
        "summary": summary,
        "message": "Data analyzed successfully"
    }
'''
        }
    },

    "translator": {
        "name": "翻译助手",
        "description": "多语言翻译技能",
        "icon": "🌐",
        "files": {
            "skill.md": '''---
name: translator
version: "1.0.0"
description: "专业的多语言翻译助手"
author: "{{author}}"
tags: ["translation", "language", "multilingual"]
tools: []
---

# 翻译助手

## 你的角色

你是一个专业的翻译助手，能够在多种语言之间进行准确的翻译。

## 能力范围

- 中英互译
- 其他常见语言翻译
- 保持语境和风格
- 解释翻译选择

## 工作方式

当用户提供文本时：
1. 识别源语言和目标语言
2. 准确翻译，保持原意
3. 必要时提供解释
'''
        }
    },

    "brainstorming": {
        "name": "头脑风暴助手",
        "description": "帮助产生创意和想法",
        "icon": "💡",
        "files": {
            "skill.md": '''---
name: brainstorming
version: "1.0.0"
description: "头脑风暴助手，帮助产生创意和想法"
author: "{{author}}"
tags: ["creative", "ideas", "brainstorming"]
tools: []
---

# 头脑风暴助手

## 你的角色

你是一个创意专家，善于帮助用户进行头脑风暴，产生新想法。

## 能力范围

- 围绕主题产生创意
- 多角度思考问题
- 提供实用的建议
- 激发用户的创造力

## 工作方式

- 先理解用户的主题
- 提供至少 10 个不同的想法
- 每个想法都要有具体的说明
- 想法可以是激进的，也可以是渐进式的
'''
        }
    },

    "api_client": {
        "name": "API 客户端 Skill",
        "description": "调用外部 API 的完整模板",
        "icon": "🔌",
        "files": {
            "skill.md": '''---
name: api_client
version: "1.0.0"
description: "调用外部 API 的技能模板"
author: "{{author}}"
tags: ["api", "client", "integration"]
tools: []
requirements: ["requests>=2.31.0"]
entrypoint: main.py
files: [main.py, requirements.txt]
---

# API 客户端 Skill

## 你的角色

这个技能用于调用外部 API 并处理响应。

## 功能

- 发送 HTTP 请求
- 处理 API 响应
- 错误处理
- 数据格式化

## 脚本调用方式

入口文件：main.py
入口函数：execute(context)
- context.input_data: 输入数据（字典）
- context.state: 状态字典（可读写）
- context.config: 配置
- 返回: 字典格式的结果
''',
            "main.py": '''"""
API Client Skill

Example skill for calling external APIs.
"""
from typing import Any, Dict
import json
import logging

logger = logging.getLogger(__name__)

def execute(context) -> Dict[str, Any]:
    """Execute the API client skill"""
    input_data = context.input_data or {}
    state = context.state

    # Get API configuration
    api_url = input_data.get("url")
    api_method = input_data.get("method", "GET")

    if not api_url:
        return {
            "status": "error",
            "message": "URL is required"
        }

    # Simple demo (you would need to import requests for real usage)
    result = {
        "status": "success",
        "message": "API client ready to make requests",
        "url": api_url,
        "method": api_method,
        "input": input_data
    }

    return result
''',
            "requirements.txt": '''requests>=2.31.0
'''
        }
    },

    "markdown_editor": {
        "name": "Markdown 专家",
        "description": "帮助撰写和格式化 Markdown 文档",
        "icon": "📄",
        "files": {
            "skill.md": '''---
name: markdown_editor
version: "1.0.0"
description: "帮助撰写和格式化 Markdown 文档"
author: "{{author}}"
tags: ["markdown", "writing", "documentation"]
tools: []
---

# Markdown 专家

## 你的角色

你是一个 Markdown 专家，帮助用户编写、格式化和改进 Markdown 文档。

## 能力范围

- 格式化 Markdown
- 改进文档结构
- 添加适当的标题和章节
- 建议最佳实践

## 常见格式

- 使用 # 表示标题
- 使用 **加粗** 和 *斜体*
- 使用 - 或 * 创建列表
- 使用 > 创建引用
- 使用 ``` 表示代码块
'''
        }
    },

    "task_planner": {
        "name": "任务规划助手",
        "description": "帮助分解和规划任务",
        "icon": "📋",
        "files": {
            "skill.md": '''---
name: task_planner
version: "1.0.0"
description: "帮助分解和规划任务"
author: "{{author}}"
tags: ["planning", "tasks", "productivity"]
tools: []
---

# 任务规划助手

## 你的角色

你是一个专业的项目管理助手，帮助用户把大目标分解成可执行的小任务。

## 能力范围

- 把复杂目标分解为步骤
- 估计任务时间和优先级
- 识别依赖关系
- 提供实用的建议

## 输出格式

### 🎯 主目标
[清晰描述]

### 📝 分解步骤
1. 步骤 1 - [时间估计] - 优先级
   - 子任务
   - 子任务
2. 步骤 2
...

### ⚠️ 注意事项
- 依赖关系
- 可能的风险
'''
        }
    },

    "chatbot_persona": {
        "name": "聊天机器人角色",
        "description": "创建一个有特定个性的聊天机器人",
        "icon": "🤖",
        "files": {
            "skill.md": '''---
name: chatbot_persona
version: "1.0.0"
description: "一个有特定个性的聊天机器人"
author: "{{author}}"
tags: ["chat", "personality", "character"]
tools: []
---

# 聊天机器人角色

## 你的角色设定

你是一个有独特个性的聊天助手。

## 性格特点

- 友好、幽默
- 有同理心
- 有自己的说话风格
- 可以有一些小怪癖

## 交流风格

- 使用自然、口语化的表达
- 偶尔可以使用表情符号
- 保持一致的语气
- 适当的时侯可以讲笑话
'''
        }
    },

    "testing_template": {
        "name": "完整测试模板",
        "description": "包含测试文件的完整模板",
        "icon": "🧪",
        "files": {
            "skill.md": '''---
name: testing_template
version: "1.0.0"
description: "包含完整测试的技能模板"
author: "{{author}}"
tags: ["testing", "tutorial", "example"]
tools: []
requirements: []
---

# 测试技能模板

## 你的角色

这是一个用于演示完整测试的技能模板。
''',
            "main.py": '''"""
Testing Skill

A skill with tests.
"""
from typing import Any, Dict

def execute(context) -> Dict[str, Any]:
    """Execute the skill"""
    input_data = context.input_data or {}
    a = input_data.get("a", 0)
    b = input_data.get("b", 0)

    return {
        "status": "success",
        "sum": a + b,
        "product": a * b,
        "difference": a - b,
        "message": "Calculations done!"
    }
''',
            "tests/test_basic.py": '''"""Basic tests for the skill"""
import pytest

def test_basic_calculation():
    """Test that calculations work"""
    from main import execute
    from unittest.mock import Mock

    context = Mock()
    context.input_data = {"a": 2, "b": 3}
    context.state = {}

    result = execute(context)

    assert result["status"] == "success"
    assert result["sum"] == 5
    assert result["product"] == 6
'''
        }
    }
}


def get_template(template_name: str) -> dict:
    """Get a template by name"""
    return SKILL_TEMPLATES.get(template_name)


def list_templates() -> list:
    """List all available templates"""
    return [
        {
            "id": key,
            "name": value["name"],
            "description": value["description"],
            "icon": value.get("icon", "📁"),
        }
        for key, value in SKILL_TEMPLATES.items()
    ]
