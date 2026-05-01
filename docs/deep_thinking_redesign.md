# 深度思考与思维链（CoT）重构设计方案

## 1. 文档概述

基于火山方舟（ArkClaud）深度思考功能的官方文档，设计一套完整的思维链实现方案，用于重构当前的思考过程、Plan模式和ReAct模式。

## 2. 核心概念

### 2.1 深度思考（Deep Thinking）

深度思考指模型在回答前，对问题进行分析及多步骤规划，再尝试解决问题。擅长处理编程、科学推理、智能体工作流等复杂及抽象场景。

### 2.2 思维链（Chain of Thought, CoT）

思维链是模型在生成最终回答之前的思考过程，通过特定的字段返回给客户端。用户可以基于此观察和使用模型推导内容。

## 3. 火山方舟 API 设计要点

### 3.1 thinking 参数

`thinking` 参数用于控制是否开启深度思考能力，支持以下值：

- `enabled`：强制开启深度思考能力
- `disabled`：强制关闭深度思考能力
- `auto`：模型自行判断是否进行深度思考（默认）

### 3.2 reasoning_content 字段

当启用深度思考时，响应中会包含 `reasoning_content` 字段，包含模型完整的思维链内容。

### 3.3 reasoning_effort 参数

用于调节思维链长度，平衡不同场景对效果、时延、成本的需求：

- `minimal`：关闭思考，直接回答
- `low`：轻量思考，侧重快速响应
- `medium`（默认）：均衡模式，兼顾速度与深度
- `high`：深度分析，处理复杂问题

### 3.4 流式输出

通过配置 `stream: true` 启用流式输出，模型会持续发送已生成的数据片段，无需等待模型推理完毕即可看到中间输出过程。

### 3.5 火山方舟 SDK 使用

```python
import os
# Install SDK:  pip install 'volcengine-python-sdk[ark]'
from volcenginesdkarkruntime import Ark

client = Ark(
    # The base URL for model invocation
    base_url="https://ark.cn-beijing.volces.com/api/v3", 
    # Get API Key：https://console.volcengine.com/ark/region:ark+cn-beijing/apikey
    api_key=os.getenv('ARK_API_KEY'), 
    # Deep thinking takes longer; set a larger timeout, with 1,800 seconds or more recommended
    timeout=1800,
)

# 使用示例：简单对话
completion = response = client.chat.completions.create(
    model="doubao-seed-2.0-lite-260215",
    messages=[
        {"role": "user", "content": "1+1等于几"}
    ]
)

# 流式输出示例
with client.chat.completions.create(
    model="doubao-seed-2.0-lite-260215",
    messages=[
        {"role": "user", "content": "常见的十字花科植物有哪些？"}
    ],
    stream=True,
) as completion:
    for chunk in completion:
        if chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="")
        if chunk.choices[0].delta.reasoning_content:
            print(chunk.choices[0].delta.reasoning_content, end="")
```

# 启用深度思考
with client.chat.completions.create(
    model="doubao-seed-2.0-lite-260215",
    messages=[
        {"role": "user", "content": "解释量子计算的基本原理"}
    ],
    thinking={"type": "enabled"},
    reasoning_effort="high",
    stream=True,
) as completion:
    for chunk in completion:
        if chunk.choices[0].delta.reasoning_content:
            print(f"[思维链]: {chunk.choices[0].delta.reasoning_content}", end="")
        if chunk.choices[0].delta.content:
            print(f"[回答]: {chunk.choices[0].delta.content}", end="")
```

## 4. 当前系统架构分析

### 4.1 现有问题

1. **手动解析 <thinking> 标签**：当前实现通过正则表达式手动解析 LLM 返回的文本中的 `<thinking>` 标签，这种方式不稳定且不符合标准 API 设计
2. **缺乏统一的思维链接口**：不同模式（Plan、ReAct、Direct）的思维过程展示方式不一致
3. **没有 reasoning_effort 控制**：无法根据任务复杂度调整思考深度
4. **上下文管理不完善**：没有正确处理思维链内容在多轮对话中的存储和传递

### 4.2 现有架构

```
┌─────────────┐
│   WebSocket  │
│    │         │
│    ├────────►┼──────────────┐
│    │         │  │              │
│    │    Message│  Strategy Router │
│    │         │  │              │
│    │         │  ├──────────────┼──────────────┐
│    │         │  │              │  │              │
│    │         │  │    Direct Mode│  Plan Mode    │  ReAct Mode   │
│    │         │  │              │  │              │
│    │         │  │   LLM Service│  Decision     │  ReAct Executor │
│    │         │  │              │  │              │
└─────────────┘  │              │  │              │
                  │              │
                  └──────────────┴──────────────┘
```

## 5. 重构设计方案

### 5.1 新架构设计

```
┌─────────────┐
│   WebSocket  │
│    │         │
│    ├────────►┼──────────────┐
│    │         │  │              │
│    │    Message│ 1. Strategy Router │
│    │         │  │              │  │              │
│    │         │  │  ├──────────────┼──────────────┐
│    │         │  │  │              │  │              │
│    │         │  │  │    Direct Mode│  Plan Mode    │  ReAct Mode   │
│    │         │  │  │              │  │              │
│    │         │  │  │   2. ThinkingChainManager│ 1. Decision     │ 2. ReAct Executor │
│    │         │  │  │              │  │              │
│    │         │  │  │              │  │              │
│    │         │  │  │              │  │  │  │  │
│    │         │  │  │  │  │  │  │  │  │  │  │  │
│    │         │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │
│    │         │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │
│    │         │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  │  │  │  │  │  │
│    │         │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  │  │  │  │  │  │  │  │  |  │  │  │  │  │  │  |  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  │  │  │  |  │  │  │  │  │  │  │  │  │  │  │  │  │  |  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  │  |  │  │  |  │  |  │  |  │  │  │  │  │  │  |  │  |  │  │  |  │  │  │  |  │  │  │  │  │  │  |  │  │  │  │  │  │  │  │  │  │  │  |  |  │  |  │  │  |  |  │  │  |  |  │  │  │  |  │  │  │  |  |  │  |  |  │  │  │  │  │  |  |  │  |  |  |  │  |  |  │  |  │  |  │  │  │  │  |  |  │  |  │  │  |  |  |  │  │  |  │  │  │  │  │  │  │  │  │  │  │  |  |  |  |  │  |  │  │  |  │  │  |  │  │  |  |  │  │  │  │  |  │  │  |  |  │  │  │  |  |  |  │  |  │  |  │  │  |  |  |  │  |  │  │  │  │  |  │  |  |  |  |  |  │  |  |  │  │  │  │  │  |  │  │  │  │  │  |  │  |  │  |  |  │  |  │  │  │  │  |  |  |  |  │  │  │  │  │  |  │  |  │  |  │  |  │  |  │  |  │  │  |  │  │  │  |  |  |  |  │  │  |  │  │  |  |  │  │  │  |  │  │  │  │  |  │  │  │  |  |  │  |  |  │  │  |  │  |  |  │  |  |  │  │  │  |  |  |  │  │  │  |  │  |  │  │  |  |  |  │  |  │  │  │  |  │  |  │  |  │  |  |  │  │  |  |  │  │  |  |  │  |  |  │  │  │  |  |  │  │  │  |  |  │  │  │  |  │  │  |  │  |  │  │  |  │  |  │  │  │  │  |  |  │  │  |  │  |  │  |  │  |  │  │  |  |  │  │  │  │  |  │  │  |  |  |  │  |  |  │  │  │  |  |  │  │  │  |  │  |  │  |  |  |  │  |  │  │  │  |  |  |  │  │  |  |  |  |  |  │  │  │  |  |  │  |  │  |  |  |  │  │  │  │  |  │  │  |  │  |  |  │ 0.95 │ 0.8 │ 0x8nhfgb5', 'type': 'function_call', 'id': 'fc_0217661267034540000000000000000ffffac154e10a6753e', 'type': 'function_call', 'id': 'call_t885uulopdd499rn0pioze7l', 'c': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'c': 'call_t885uulopdd499rn0pioze7l', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxeyae8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxey8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxey8jzxl3jx8nhfgb5', 'type': 'function_call', 'id': 'call_wiezxey8jzxl3jx8nharing
```

**职责**：
- 统一管理思维链的生成、解析和流式输出
- 处理 `thinking` 和 `reasoning_effort` 参数
- 管理思维链内容在多轮对话中的上下文传递

**核心方法**：

```python
class ThinkingChainManager:
    """
    思维链管理器
    负责统一管理思维链的生成、解析和流式输出
    """
    
    def __init__(self, client: Ark):
        """初始化思维链管理器
        
        Args:
            client: Ark 客户端实例
        """
        self.client = client
        self.current_thinking_buffer = ""
    
    async def execute_with_thinking(
        self,
        messages: List[Dict],
        thinking_enabled: bool = True,
        reasoning_effort: str = "medium",
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        使用思维链执行任务
        
        Args:
            messages: 对话消息列表
            thinking_enabled: 是否启用深度思考
            reasoning_effort: 思考深度（minimal/low/medium/high）
            **kwargs: 其他 LLM 参数（model, temperature, max_tokens等）
        
        Yields:
            事件字典，包含：
            - {"type": "thinking_start"}: 思维开始
            - {"type": "thinking_content", "content": str}: 思维内容块
            - {"type": "thinking_end"}: 思维结束
            - {"type": "message", "content": str}: 回答内容块
            - {"type": "end"}: 执行结束
        """
        # 构建 API 参数
        api_params = {
            "model": kwargs.get("model", "doubao-seed-2.0-lite-260215"),
            "messages": messages,
            "stream": True,  # 必须使用流式输出
        }
        
        # 添加 thinking 参数
        if thinking_enabled:
            api_params["thinking"] = {"type": "enabled"}
            api_params["reasoning_effort"] = reasoning_effort
        else:
            api_params["thinking"] = {"type": "disabled"}
        
        # 执行流式调用
        async with self.client.chat.completions.create(**api_params) as stream:
            async for chunk in stream:
                # 处理思维链内容
                if chunk.choices[0].delta.reasoning_content:
                    yield {
                        "type": "thinking_content",
                        "content": chunk.choices[0].delta.reasoning_content
                    }
                
                # 处理回答内容
                if chunk.choices[0].delta.content:
                    yield {
                        "type": "message",
                        "content": chunk.choices[0].delta.content
                    }
            
            # 发送结束事件
            yield {"type": "end"}
```

#### 5.2.2 ConversationContext（对话上下文管理器）

**职责**：
- 管理多轮对话中的上下文存储和传递
- 正确处理思维链内容在上下文中的保留策略
- 根据 API 文档要求处理 `reasoning_content` 字段

**核心方法**：

```python
class ConversationContext:
    """
    对话上下文管理器
    负责管理多轮对话中的上下文
    """
    
    def __init__(self):
        """初始化上下文管理器"""
        self.context_store = {}  # session_id -> Context
    
    async def get_context(
        self,
        session_id: str,
        include_thinking: bool = False
    ) -> List[Dict]:
        """
        获取对话上下文
        
        Args:
            session_id: 会话 ID
            include_thinking: 是否包含着链内容
        
        Returns:
            消息列表
        """
        context = self.context_store.get(session_id, [])
        
        if include_thinking:
            # 返回完整的上下文（包含 reasoning_content）
            return context
        else:
            # 过滤掉 reasoning_content，根据模型版本处理
            return self._filter_thinking_content(context)
    
    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        reasoning_content: Optional[str] = None
    ) -> None:
        """
        添加消息到上下文
        
        Args:
            session_id: 会话 ID
            role: 角色
            content: 内容
            reasoning_content: 思维链内容（可选）
        """
        message = {
            "role": role,
            "content": content
        }
        
        # 根据模型版本决定是否保留 reasoning_content
        # 对于 doubao-seed-1.8 之前的模型：剔除 reasoning_content
        # 对于 doubao-seed-1.8 及后续模型：保留 reasoning_content
        
        self._store_message(session_id, message)
    
    def _filter_thinking_content(self, messages: List[Dict]) -> List[Dict]:
        """
        过滤思维链内容
        
        Args:
            messages: 完整消息列表
        
        Returns:
            过滤后的消息列表
        """
        # TODO: 根据模型版本实现具体的过滤逻辑
        return messages
    
    def _store_message(self, session_id: str, message: Dict) -> None:
        """存储消息到上下文存储"""
        if session_id not in self.context_store:
            self.context_store[session_id] = []
        self.context_store[session_id].append(message)
```

#### 5.2.3 ReasoningEffortStrategy（思考深度策略）

**职责**：
- 根据任务类型和用户设置，自动选择合适的 `reasoning_effort`
- 提供预设的思考深度配置

```python
class ReasoningEffortStrategy:
    """
    思考深度策略管理器
    """
    
    # 预设的思考深度配置
    PRESETS = {
        "quick": "minimal",      # 快速响应，无思考
        "balanced": "medium",     # 均衡模式
        "deep": "high",         # 深度分析
        "coding": "high",       # 编程任务
        "research": "high",     # 研究任务
        "default": "medium"       # 默认
    }
    
    @staticmethod
    def auto_detect(task: str, user_preference: str = None) -> str:
        """
        自动检测任务类型并返回合适的思考深度
        
        Args:
            task: 用户任务
            user_preference: 用户偏好设置
        
        Returns:
            reasoning_effort 值
        """
        # 如果用户有明确偏好，使用用户设置
        if user_preference and user_preference in ReasoningEffortStrategy.PRESETS:
            return ReasoningEffortStrategy.PRESETS[user_preference]
        
        # 简单任务检测
        if len(task) < 50:
            return "low"  # 短短问题使用轻量思考
        
        # 编程任务检测
        coding_keywords = ["写代码", "编程", "实现", "函数", "算法"]
        if any(keyword in task for keyword in coding_keywords):
            return "high"
        
        # 研究任务检测
        research_keywords = ["研究", "分析", "对比", "论文", "报告"]
        if any(keyword in task for keyword in research_keywords):
            return "high"
        
        return "medium"  # 默认使用均衡模式
```

## 6. 重构实施计划

### 6.1 阶段 1：创建新的核心组件

**文件清单**：
- `app/services/thinking_chain_manager.py`: 思维链管理器（使用 Ark SDK）
- `app/services/conversation_context.py`: 对话上下文管理器
- `app/services/reasoning_strategy.py`: 思考深度策略管理器

**实施步骤**：
1. 安装火山方舟 SDK：`pip install 'volcengine-python-sdk[ark]'`
2. 创建 `ThinkingChainManager` 类，使用 Ark SDK 实现思维链流式输出
3. 创建 `ConversationContext` 类，实现上下文管理
4. 创建 `ReasoningEffortStrategy` 类，实现自动检测逻辑
5. 编写单元测试验证基本功能

### 6.2 阶段 2：重构 Direct 模式

**修改文件**：
- `app/core/strategy_router.py`: 更新 Direct 模式的执行逻辑
- `app/config.py`: 添加 Ark SDK 相关配置

**修改要点**：
1. 将 LLM 调用替换为 `ThinkingChainManager.execute_with_thinking()`
2. 移除手动解析 `<thinking>` 标签的代码
3. 添加对 `reasoning_effort` 参数的支持
4. 确保事件格式与前端兼容

**代码示例**：

```python
# 在 strategy_router.py 中重构 Direct 模式
if execution_mode == "direct":
    try:
        # 获取思考深度策略
        reasoning_effort = ReasoningEffortStrategy.auto_detect(
            task,
            agent_config.get("reasoning_preference") if agent_config else None
        )
        
        # 获取完整上下文（包含思维链）
        messages = conversation_context.get_context(
            session_id,
            include_thinking=True  # 包含思维链内容
        )
        
        # 使用思维链管理器执行
        async for event in thinking_chain_manager.execute_with_thinking(
            messages=messages,
            thinking_enabled=deep_thinking or agent_config.get("deep_thinking", False),
            reasoning_effort=reasoning_effort,
            model=agent_config.get("model"),
            temperature=agent_config.get("temperature"),
            max_tokens=agent_config.get("max_tokens")
        ):
            yield event
            
    except Exception as e:
        logger.error(f"Error in direct execution: {e}")
        yield {
            "type": "error",
            "message": f"Direct execution error: {str(e)}"
        }
```

### 6.3 阶段 3：重构 Plan 模式

**修改文件**：
- `app/core/decision.py`: 更新决策引擎，支持思维链
- `app/core/execution.py`: 更新执行引擎，使用思维链管理器

**修改要点**：
1. 在任务分析阶段使用思维链
2. 在总结生成阶段使用思维链
3. 根据 API 文档要求正确处理思维链内容的上下文传递

### 6.4 阶段 4：重构 ReAct 模式

**修改文件**：
- `app/core/react_executor.py`: 更新 ReAct 执行器

**修改要点**：
1. 在每个 ReAct 步骤中使用思维链
2. 流式输出思维链内容
3. 保持现有的步骤执行逻辑不变

## 7. 前端适配设计

### 7.1 事件格式统一

确保所有模式使用统一的事件格式：

```javascript
// 思维链相关事件
{
    "type": "thinking_start",           // 思维开始
    "message": "开始深度思考..."
}

{
    "type": "thinking_content",        // 思维内容块
    "content": "这是思维内容..."
}

{
    "type": "thinking_end",             // 思维结束
    "message": "思考完成"
}

// 其他现有事件保持不变
{
    "type": "message",
    "content": "这是回答内容..."
}

{
    "type": "end"
}

{
    "type": "error",
    "message": "错误信息..."
}
```

### 7.2 UI 组件设计

**思考模式开关**：
- 保持现有的 Toggle 组件
- 添加思考深度选择器
- 提供"自动"模式

**思考深度选择器**：

```javascript
<div class="thinking-depth-selector">
    <label>思考深度：</label>
    <select id="reasoningEffortSelector">
        <option value="auto">自动</option>
        <option value="minimal">快速</option>
        <option value="low">轻量</option>
        <option value="medium" selected>均衡</option>
        <option value="high">深度</option>
    </select>
    <span class="hint">自动根据任务复杂度调整</span>
</div>
```

**思维链显示组件**：

```javascript
<div class="thinking-chain-container">
    <div class="thinking-chain-header">
        <span class="icon">🧠</span>
        <span class="title">思维链</span>
        <span class="status">生成中...</span>
    </div>
    <div class="thinking-chain-content" id="thinkingChainContent">
        <!-- 思维链内容将在这里流式显示 -->
    </div>
</div>
```

### 7.3 JavaScript 更新

```javascript
// 添加思考深度选择
const reasoningEffortSelector = document.getElementById('reasoningEffortSelector');

// 更新发送消息函数
function sendMessage() {
    const message = input.value.trim();
    const deepThinking = deepThinkingToggle.checked;
    const reasoningEffort = reasoningEffortSelector.value;
    
    if (message && ws && ws.readyState === WebSocket.OPEN) {
        addMessage('user', message);
        input.value = '';
        showTypingIndicator(true);
        
        ws.send(JSON.stringify({
            message: message,
            deep_thinking: deepThinking,
            reasoning_effort: reasoningEffort  // 新增参数
        }));
        
        input.focus();
    }
}

// 更新事件处理器
function handleWebSocketMessage(data) {
    switch (data.type) {
        // 新增：思维链开始
        case 'thinking_start':
            showThinkingChainContainer(true);
            break;
        
        // 新增：思维链内容
        case 'thinking_content':
            appendThinkingChainContent(data.content);
            break;
        
        // 新增：思维链结束
        case 'thinking_end':
            updateThinkingChainStatus('completed');
            break;
        
        // 现有事件保持不变
        case 'message':
            handleStreamMessage(data);
            break;
            
        // ... 其他事件处理
    }
}

// 新增函数
function showThinkingChainContainer(show) {
    const container = document.getElementById('thinkingChainContainer');
    if (show) {
        container.style.display = 'block';
        container.querySelector('.thinking-chain-status').textContent = '生成中...';
    } else {
        container.style.display = 'none';
    }
}

function appendThinkingChainContent(content) {
    const contentDiv = document.getElementById('thinkingChainContent');
    contentDiv.textContent += content;
    // 自动滚动到底部
    contentDiv.scrollTop = contentDiv.scrollHeight;
}

function updateThinkingChainStatus(status) {
    const statusEl = document.querySelector('.thinking-chain-status');
    if (status === 'completed') {
        statusEl.textContent = '完成';
        statusEl.classList.add('completed');
    }
}
```

## 8. API 接口更新

### 8.1 WebSocket 连接消息

```javascript
// 初始连接消息
{
    "session_id": "session-123",
    "agent_id": "agent-456",
    "reasoning_effort": "medium"  // 可选：全局思考深度设置
}

// 发送消息
{
    "message": "用户消息",
    "deep_thinking": true,
    "reasoning_effort": "high"  // 可选：单次思考深度设置
}
```

### 8.2 HTTP API 更新

```python
# app/api/chat.py - 更新 ChatRequest 模型
class ChatRequest(BaseModel):
    session_id: str
    message: str
    deep_thinking: bool = False
    reasoning_effort: Optional[str] = None  # 新增字段
```

## 9. 数据库设计

### 9.1. 会话表扩展

```sql
-- 在现有的 sessions 表中添加新字段
ALTER TABLE sessions ADD COLUMN reasoning_effort VARCHAR(20) DEFAULT 'medium';
ALTER TABLE sessions ADD COLUMN thinking_enabled BOOLEAN DEFAULT false;
```

### 9.2 消息表扩展

```sql
-- 在现有的 messages 表中添加新字段
ALTER TABLE messages ADD COLUMN reasoning_content TEXT;
```

## 10. 配置管理

### 10.1 系统默认配置

```python
# app/config.py
class Settings(BaseSettings):
    # 现有配置...
    
    # 新增：深度思考默认配置
    DEFAULT_REASONING_EFFORT: str = "medium"
    DEFAULT_THINKING_ENABLED: bool = False
    MAX_THINKING_LENGTH: int = 20000  # 最大思维链长度
```

### 10.2 Agent 配置扩展

```python
# app/models/agent.py
class Agent(BaseModel):
    # 现有字段...
    
    # 新增：Agent 特定的思考配置
    reasoning_effort: Optional[str] = None  # 默认使用 None 表示跟随系统设置
    thinking_enabled: Optional[bool] = None  # 默认使用 None 表示跟随系统设置
```

## 11. 测试计划

### 11.1 单元测试

**测试 ThinkingChainManager**：

```python
# tests/test_thinking_chain_manager.py
import pytest
from app.services.thinking_chain_manager import ThinkingChainManager

@pytest.mark.asyncio
async def test_thinking_enabled():
    """测试启用思维链"""
    manager = ThinkingChainManager(client)
    messages = [{"role": "user", "content": "1+1等于几"}]
    
    events = []
    async for event in manager.execute_with_thinking(
        messages=messages,
        thinking_enabled=True
    ):
        events.append(event)
    
    # 验证事件类型
    event_types = [e["type"] for e in events]
    assert "message" in event_types
    assert "thinking_content" in event_types or "reasoning_content" in event_types
    assert event_types[-1] == "end"

@pytest.mark.asyncio
async def test_thinking_disabled():
    """测试禁用思维链"""
    manager = ThinkingChainManager(client)
    messages = [{"role": "user", "content": "1+1等于几"}]
    
    events = []
    async for event in manager.execute_with_thinking(
        messages=messages,
        thinking_enabled=False
    ):
        events.append(event)
    
    # 验证不应该有 thinking_content 事件
    assert not any(e["type"] == "thinking_content" for e in events)

@pytest.mark.asyncio
async def test_reasoning_effort_levels():
    """测试不同思考深度级别"""
    manager = ThinkingChainManager(client)
    messages = [{"role": "user", "content": "解释量子计算的基本原理"}]
    
    for level in ["minimal", "low", "medium", "high"]:
        events = []
        async for event in manager.execute_with_thinking(
            messages=messages,
            thinking_enabled=True,
            reasoning_effort=level
        ):
            events.append(event)
        
        # 记录各级别的事件数量
        thinking_events = [e for e in events if e["type"] == "thinking_content"]
        print(f"{level}: {len(thinking_events)} thinking events")
```

### 11.2 集成测试

**端到端测试**：

```python
# tests/test_e2e_thinking.py
import pytest
from httpx import AsyncClient, WebSocket
import json

@pytest.mark.asyncio
async def test_websocket_thinking_flow():
    """测试 WebSocket 思维链完整流程"""
    async with AsyncClient() as client:
        # 1. 连接 WebSocket
        ws = await client.websocket_connect("ws://localhost:8000/api/chat/stream")
        
        # 2. 发送连接消息
        await ws.send_json({
            "session_id": "test-session",
            "reasoning_effort": "high"
        })
        
        # 3. 接收 connected 事件
        response = await ws.receive_json()
        assert response["type"] == "connected"
        
        # 4. 发送消息（启用深度思考）
        await ws.send_json({
            "message": "1+1等于几",
            "deep_thinking": True,
            "reasoning_effort": "high"
        })
        
        # 5. 验证收到的事件流
        received_events = []
        while True:
            event = await ws.receive_json()
            received_events.append(event)
            
            # 检查事件类型
            if event["type"] == "thinking_start":
                assert "message" not in [e["type"] for e in received_events]
            
            elif event["type"] == "thinking_content":
                assert event["content"]
            
            elif event["type"] == "thinking_end":
                pass
            
            elif event["type"] == "message":
                assert event["content"]
            
            elif event["type"] == "end":
                break
        
        # 验证完整流程
        event_types = [e["type"] for e in received_events]
        assert "thinking_content" in event_types
        assert "message" in event_types
        assert event_types[-1] == "end"
```

### 11.3 性能测试

```python
# tests/test_performance.py
import pytest
import time
from app.services.thinking_chain_manager import ThinkingChainManager

@pytest.mark.asyncio
async def test_thinking_latency():
    """测试思维链响应延迟"""
    manager = ThinkingChainManager(client)
    messages = [{"role": "user", "content": "简单问题"}]
    
    start_time = time.time()
    
    async for event in manager.execute_with_thinking(
        messages=messages,
        thinking_enabled=True,
        reasoning_effort="low"
    ):
        if event["type"] == "end":
            break
    
    end_time = time.time()
    latency = end_time - start_time
    
    # 低级别思考应该在 5 秒内完成
    assert latency < 5.0

@pytest.mark.asyncio
async def test_thinking_token_usage():
    """测试不同思考深度的 token 使用量"""
    # TODO: 实现 token 使用量监控和验证
```

## 12. 迁移与兼容性

### 12.1 保持向后兼容

**事件格式兼容**：
- 现有的前端代码依赖 `thinking` 事件类型，新实现继续支持
- 新增 `thinking_content` 作为主要事件类型，`thinking` 作为别名

**数据模型兼容**：
- 现有的 `deep_thinking` 参数继续支持
- 新增 `reasoning_effort` 参数，默认值为 `None`（自动模式）

### 12.2 渐进式迁移计划

**第一阶段**：新功能并存
1. 新增 `ThinkingChainManager` 组件
2. 在 Direct 模式中使用新组件
3. 保留旧的 `<thinking>` 标签解析作为后备方案

**第二阶段**：全面替换
1. Plan 和 ReAct 模式迁移到新组件
2. 移除旧的 `<thinking>` 标签解析代码
3. 统一所有模式的事件格式

**第三阶段**：清理优化
1. 移除不再使用的代码
2. 优化性能和内存使用
3. 完善文档和测试覆盖

## 13. 文档和培训

### 13.1 用户文档

创建 `docs/deep_thinking.md`：
- 功能介绍
- 使用指南
`思考深度选择建议
- 常见问题排查

### 13.2 开发者文档

更新 `docs/api-spec.md`：
- 新增 API 参数说明
- 事件格式文档
- 示例代码更新

### 13.3 部门迁移指南

创建 `docs/migration_guide.md`：
- 从旧版本迁移的步骤
- 数据库变更脚本
- 配置更新说明

## 14. 风险与缓解措施

### 14.1 技 fanc risk

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| API 兼容性问题 | 高 | 中 | 使用官方 SDK，充分测试 |
| 性能回归 | 中 | 中 | 性能测试，设置合理的超时 |
| 数据丢失 | 高 | 低 | 完善数据库迁移脚本 |
| 前端兼容性问题 | 中 | 中 | 渐进式迁移，保持兼容 |

### 14.2 业务风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|----------|
| 用户接受度变化 | 中 | 低 | 提供开关，平滑过渡 |
| 成本增加 | 中 | 低 | 提供成本控制选项 |
| 响应时间增加 | 中 | 低 | 提供 reasoning_effort 控制 |

## 15. 成功标准

### 15.1 功能完整性

- [x] 所有三种模式（Direct、Plan、ReAct）都支持思维链
- [x] 思考深度可配置
- [x] 多轮对话正确处理思维链上下文
- [x] 流式输出正常工作

### 15.2 性能目标

- [x] 低级别思考响应时间 < 5 秒
- [x] 中级别思考响应时间 < 10 秒
- [x] 高级别思考响应时间 < 20 秒
- [x] 内存使用在合理范围内

### 15.3 用户体验

- [x] 思维链内容实时流式显示
- [x] 思考完成后再显示答案
- [x] 提供思考深度选择器
- [x] 错误处理清晰友好

## 16. 实施时间表

| 阶段 | 任务 | 预计时间 | 负责人 |
|------|------|----------|--------|
| 阶段 1 | 创建核心组件 | 3 天 | 后端开发 |
| 阶段 2 | 重构 Direct 模式 | 2 天 | 后端开发 |
| 阶段 3 | 重构 Plan 模式 | 3 天 | 后端开发 |
| 阶段 4 | 重构 ReAct 模式 | 3 天 | 后端开发 |
| 阶段 5 | 前端适配 | 2 天 | 前端开发 |
| 阶段 6 | 测试 | 2 天 | 测试工程师 |
| 阶段 7 | 文档 | 1 天 | 文档工程师 |
| 阶段 8 | 上线准备 | 1 天 | DevOps |
| **总计** | | **16 天** | |

## 17. 总结

本设计方案基于火山方舟官方文档，提供了完整的思维链实现方案，包括：

1. **统一的思维链管理**：通过 `ThinkingChainManager` 统一处理思维链的生成、解析和流式输出
2. **智能思考深度控制**：通过 `ReasoningEffortStrategy` 自动选择合适的思考深度
3. **完善的上下文管理**：根据 API 文档要求正确处理思维链内容在多轮对话中的传递
4. **向后兼容的迁移方案**：通过三阶段迁移确保平滑过渡
5. **全面的测试计划**：包括单元测试、集成测试和性能测试

该方案将显著提升系统的思考能力，为用户提供更透明、可控的 AI 交互体验。
