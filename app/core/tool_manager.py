"""
统一的工具和技能管理器

这个模块提供统一的接口来管理：
1. 本地工具（Local Tools）- 直接在代码中定义的工具
2. MCP工具（MCP Tools）- 来自MCP服务器的工具
3. 技能工具（Skill Tools）- 用于加载和管理技能的工具

所有执行器都应该通过这个统一接口来获取可用工具。
"""
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass

from app.services.mcp_pool import mcp_client_pool
from app.skills.registry import get_skill_registry

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Optional[Callable] = None
    source: str = "unknown"  # "local", "mcp", "skill"
    server_id: Optional[str] = None
    original_name: Optional[str] = None


class UnifiedToolManager:
    """
    统一的工具管理器

    负责集中管理所有类型的工具，提供统一的访问接口。
    """

    def __init__(self):
        """初始化统一工具管理器"""
        # 本地工具（包括技能工具）
        self._local_tools: Dict[str, ToolDefinition] = {}

        # 是否已初始化技能工具
        self._skill_tools_initialized = False

        logger.info("UnifiedToolManager initialized")

    def register_local_tool(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable,
        source: str = "local"
    ):
        """
        注册本地工具

        Args:
            name: 工具名称
            description: 工具描述
            input_schema: 工具参数schema
            handler: 工具处理函数
            source: 工具来源
        """
        tool = ToolDefinition(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
            source=source,
            server_id="local" if source == "local" else source
        )
        self._local_tools[name] = tool
        logger.info(f"Registered local tool: {name} from {source}")

    def register_skill_tools(self):
        """
        注册技能相关工具

        这个方法应该在应用启动时调用一次。
        """
        if self._skill_tools_initialized:
            return

        # 注册 load_skill 工具
        async def load_skill_handler(skill_name: str) -> Dict[str, Any]:
            """加载技能的完整内容"""
            registry = get_skill_registry()
            content = registry.get_skill_content(skill_name)
            if not content:
                return {"error": f"Skill '{skill_name}' not found"}
            skill = registry.get_skill(skill_name)
            has_entrypoint = False
            if skill:
                if skill.entrypoint and __import__('pathlib').Path(skill.entrypoint).exists():
                    has_entrypoint = True
                elif skill.dir_path:
                    # Check if any executable script exists in skill directory
                    import os
                    is_windows = os.name == "nt"
                    candidates = (
                        ["main.py", "main.ps1", "main.sh"]
                        if is_windows
                        else ["main.py", "main.sh", "main.ps1"]
                    )
                    for name in candidates:
                        if __import__('pathlib').Path(skill.dir_path, name).exists():
                            has_entrypoint = True
                            break
            return {
                "skill_name": skill_name,
                "content": content,
                "has_entrypoint": has_entrypoint,
                "message": f"Successfully loaded skill: {skill_name}"
            }

        self.register_local_tool(
            name="load_skill",
            description="Load a skill's full instruction content by name. Use this when you need to use a specific skill that's listed in your available skills. After loading, if the skill has an entrypoint (has_entrypoint=true), you MUST call execute_skill to actually perform the action.",
            input_schema={
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "The name of the skill to load"
                    }
                },
                "required": ["skill_name"]
            },
            handler=load_skill_handler,
            source="skill"
        )

        # 注册 execute_skill 工具
        async def execute_skill_handler(
            skill_name: str,
            input_data: Optional[Dict[str, Any]] = None,
            session_id: Optional[str] = None
        ) -> Dict[str, Any]:
            """执行技能的入口脚本"""
            from app.skills.executor import get_skill_executor

            executor = get_skill_executor()
            result = await executor.execute(
                skill_name=skill_name,
                input_data=input_data or {},
                session_id=session_id
            )

            if result.success:
                return {
                    "status": "success",
                    "skill_name": skill_name,
                    "output": result.output,
                    "execution_time_ms": result.execution_time_ms,
                    "logs": result.logs
                }
            else:
                return {
                    "status": "error",
                    "skill_name": skill_name,
                    "error": result.error,
                    "execution_time_ms": result.execution_time_ms,
                    "logs": result.logs
                }

        self.register_local_tool(
            name="execute_skill",
            description="Execute a skill's entrypoint script (main.py, main.ps1, main.sh) to perform the actual action. Call this AFTER load_skill when the skill has an entrypoint. Pass the user's intent as input_data (e.g. {\"command\": \"set brightness to 0\"} or {\"instruction\": \"调低亮度\"}).",
            input_schema={
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "The name of the skill to execute"
                    },
                    "input_data": {
                        "type": "object",
                        "description": "Input data for the skill execution, typically containing the user's command or instruction (e.g. {\"command\": \"set brightness to 50\"})"
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Optional session ID for state persistence across multiple calls"
                    }
                },
                "required": ["skill_name"]
            },
            handler=execute_skill_handler,
            source="skill"
        )

        self._skill_tools_initialized = True
        logger.info("Skill tools registered (load_skill, execute_skill)")

    async def get_available_tools(
        self,
        enabled_mcp_servers: Optional[List[str]] = None,
        allowed_tools: Optional[List[str]] = None
    ) -> Dict[str, ToolDefinition]:
        """
        获取所有可用的工具

        Args:
            enabled_mcp_servers: 启用的MCP服务器ID列表，如果为None则不包含MCP工具
            allowed_tools: 工具白名单，如果为None则不过滤

        Returns:
            工具名称到工具定义的字典
        """
        tools: Dict[str, ToolDefinition] = {}

        # 1. 总是添加本地工具
        for tool_name, tool_def in self._local_tools.items():
            tools[tool_name] = tool_def

        # 2. 从MCP服务器添加工具（如果有指定启用的服务器）
        if enabled_mcp_servers and isinstance(enabled_mcp_servers, list) and len(enabled_mcp_servers) > 0:
            all_mcp_tools = await mcp_client_pool.get_all_tools()
            allowed_server_set = set(enabled_mcp_servers)

            for tool_name, tool_info in all_mcp_tools.items():
                tool_server_id = tool_info.get("server_id")
                if tool_server_id and tool_server_id in allowed_server_set and tool_server_id != "local":
                    # 转换为ToolDefinition
                    tools[tool_name] = ToolDefinition(
                        name=tool_name,
                        description=tool_info.get("description", ""),
                        input_schema=tool_info.get("input_schema", {}),
                        source="mcp",
                        server_id=tool_server_id,
                        original_name=tool_info.get("original_name")
                    )

        # 3. 按白名单过滤（混合模式）
        # allowed_tools=None     → 不过滤，加载已绑定server的全部tool（兼容旧行为）
        # allowed_tools=[]       → 加载已绑定server的全部tool + skill工具
        # allowed_tools=["xx"]   → 混合逻辑：白名单中的 tool 放行；
        #   对每个已绑定 server，如果没有任何 tool 被选中，则该 server 全部 tool 放行
        if allowed_tools is not None and isinstance(allowed_tools, list):
            allowed_set = set(allowed_tools)
            # 始终包含 load_skill 和 execute_skill 工具
            allowed_set.add("load_skill")
            allowed_set.add("execute_skill")

            # 找出哪些 server 的 tool 一个都没被选中（包括 allowed_tools 为空的情况）
            mcp_server_set = set(enabled_mcp_servers) if enabled_mcp_servers else set()
            servers_with_no_tools_selected = set()
            for sid in mcp_server_set:
                has_any = any(
                    v.server_id == sid and v.source == "mcp" and k in allowed_set
                    for k, v in tools.items()
                )
                if not has_any:
                    servers_with_no_tools_selected.add(sid)

            # 白名单中的 tool 放行 + 没有被选中任何 tool 的 server 全部放行
            tools = {
                k: v for k, v in tools.items()
                if k in allowed_set
                or (v.server_id in servers_with_no_tools_selected and v.source == "mcp")
            }

        logger.info(f"Available tools: {list(tools.keys())}")
        return tools

    async def get_tools_for_llm(
        self,
        enabled_mcp_servers: Optional[List[str]] = None,
        allowed_tools: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        获取LLM格式的工具列表

        Args:
            enabled_mcp_servers: 启用的MCP服务器ID列表
            allowed_tools: 工具白名单

        Returns:
            LLM格式的工具列表，适合直接传给LLM API
        """
        tools = await self.get_available_tools(enabled_mcp_servers, allowed_tools)

        llm_tools = []
        for tool_name, tool_def in tools.items():
            llm_tools.append({
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_def.description,
                    "parameters": tool_def.input_schema
                }
            })

        logger.info(f"Prepared {len(llm_tools)} tools for LLM")
        return llm_tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Any:
        """
        调用工具

        Args:
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            工具执行结果
        """
        # 先检查本地工具
        if tool_name in self._local_tools:
            tool_def = self._local_tools[tool_name]
            if tool_def.handler:
                logger.info(f"Calling local tool: {tool_name}")
                return await tool_def.handler(**arguments)

        # 否则尝试通过MCP客户端池调用
        try:
            logger.info(f"Calling MCP tool: {tool_name}")
            return await mcp_client_pool.call_tool(tool_name, arguments)
        except Exception as e:
            logger.error(f"Failed to call tool {tool_name}: {e}")
            raise ValueError(f"Tool '{tool_name}' not found or failed to execute")


# 全局单例
_tool_manager: Optional[UnifiedToolManager] = None


def get_tool_manager() -> UnifiedToolManager:
    """获取全局统一工具管理器"""
    global _tool_manager
    if _tool_manager is None:
        _tool_manager = UnifiedToolManager()
        _tool_manager.register_skill_tools()
    return _tool_manager
