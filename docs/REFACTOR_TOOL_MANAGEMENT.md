# 工具和技能管理重构说明

## 概述

本次重构统一了工具和技能的加载逻辑，解决了之前代码分散、逻辑重复的问题。

## 重构前的问题

1. **工具加载逻辑分散**：
   - `llm_service.py` 有自己的工具加载逻辑
   - `react_cot_executor.py` 有自己的工具加载逻辑  
   - `decision.py` 有自己的工具加载逻辑
   - 每个地方的过滤规则不一致

2. **技能工具特殊处理**：
   - `load_skill` 工具需要特殊注册
   - 技能和工具的关系不清晰

3. **代码重复**：
   - 同样的MCP服务器过滤逻辑在多处重复
   - 同样的工具白名单过滤逻辑在多处重复

## 重构方案

### 1. 创建统一工具管理器 `app/core/tool_manager.py`

**核心组件**：
- `UnifiedToolManager` 类：统一管理所有工具
- `ToolDefinition` 数据类：标准化工具定义
- 全局单例 `get_tool_manager()`：全局访问点

**功能**：
- ✅ 注册本地工具（`register_local_tool`）
- ✅ 自动注册技能工具（`register_skill_tools`）
- ✅ 获取可用工具（`get_available_tools`）
- ✅ 获取LLM格式工具（`get_tools_for_llm`）
- ✅ 调用工具（`call_tool`）

### 2. 更新各模块使用统一管理器

**修改的文件**：
- `app/main.py` - 使用统一管理器注册工具
- `app/core/react_cot_executor.py` - 使用统一管理器
- `app/services/llm_service.py` - 使用统一管理器
- `app/core/decision.py` - 使用统一管理器
- `app/core/react_executor.py` - 使用统一管理器

### 3. 工具分类

统一管理器将工具分为三类：

1. **本地工具（Local Tools）**：
   - 文件系统工具
   - 网络搜索工具
   - Source: `local`

2. **技能工具（Skill Tools）**：
   - `load_skill` - 加载技能内容
   - Source: `skill`

3. **MCP工具（MCP Tools）**：
   - 来自MCP服务器的工具
   - Source: `mcp`

## 工具过滤逻辑（统一）

所有执行器使用相同的过滤逻辑：

```python
1. 总是添加本地工具 + 技能工具
2. 如果有启用的MCP服务器，添加对应的MCP工具
3. 如果有工具白名单，按白名单过滤
```

## 使用示例

### 注册工具

```python
from app.core.tool_manager import get_tool_manager

tool_manager = get_tool_manager()

tool_manager.register_local_tool(
    name="my_tool",
    description="Tool description",
    input_schema={...},
    handler=my_tool_handler,
    source="local"
)
```

### 获取工具

```python
tools = await tool_manager.get_available_tools(
    enabled_mcp_servers=["server1", "server2"],
    allowed_tools=["tool1", "tool2"]
)
```

### 获取LLM格式工具

```python
llm_tools = await tool_manager.get_tools_for_llm(
    enabled_mcp_servers=enabled_servers,
    allowed_tools=allowed_tools
)
```

### 调用工具

```python
result = await tool_manager.call_tool("tool_name", {"arg1": "value1"})
```

## 技能系统工作原理

1. **Agent初始化**：
   - Agent配置关联的技能
   - 技能列表通过system_prompt告诉LLM

2. **用户提问**：
   - LLM识别需要使用某个技能
   - 调用 `load_skill("skill_name")` 工具

3. **技能加载**：
   - UnifiedToolManager处理load_skill调用
   - 从SkillRegistry获取完整技能内容

4. **技能应用**：
   - LLM获得完整技能说明
   - 按照技能指导回答用户

## 文件清单

### 新增文件
- `app/core/tool_manager.py` - 统一工具管理器

### 修改文件
- `app/main.py` - 使用统一管理器注册工具
- `app/core/react_cot_executor.py` - 使用统一管理器
- `app/services/llm_service.py` - 使用统一管理器
- `app/core/decision.py` - 使用统一管理器
- `app/core/react_executor.py` - 使用统一管理器

### 保持不变
- `app/services/mcp_pool.py` - MCP连接管理
- `app/skills/registry.py` - 技能注册管理
- 其他技能相关文件

## 优势

1. **统一逻辑**：所有地方使用相同的工具加载逻辑
2. **易于维护**：修改工具加载逻辑只需改一个地方
3. **清晰的职责划分**：
   - UnifiedToolManager: 工具管理
   - MCPClientPool: MCP连接管理
   - SkillRegistry: 技能管理
4. **更好的扩展性**：添加新工具类型只需修改一个地方
5. **技能工具自动包含**：`load_skill`工具总是可用
