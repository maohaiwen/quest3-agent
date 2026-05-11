"""
统一的工具和技能管理器

这个模块提供统一的接口来管理：
1. 本地工具（Local Tools）- 直接在代码中定义的工具
2. MCP工具（MCP Tools）- 来自MCP服务器的工具
3. 技能工具（Skill Tools）- 用于加载和管理技能的工具

所有执行器都应该通过这个统一接口来获取可用工具。
"""
import asyncio
import importlib
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
    # Plugin system: install status
    installed: bool = True
    service_name: str = ""  # Human-readable service name
    deps: List[str] = None  # Required pip packages


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
        source: str = "local",
        installed: bool = True,
        service_name: str = "",
        deps: Optional[List[str]] = None
    ):
        """
        注册本地工具

        Args:
            name: 工具名称
            description: 工具描述
            input_schema: 工具参数schema
            handler: 工具处理函数
            source: 工具来源
            installed: 是否已安装依赖
            service_name: 所属服务名称
            deps: 依赖的pip包列表
        """
        tool = ToolDefinition(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
            source=source,
            server_id="local" if source == "local" else source,
            installed=installed,
            service_name=service_name,
            deps=deps or []
        )
        self._local_tools[name] = tool
        status = "installed" if installed else "not_installed"
        logger.info(f"Registered local tool: {name} from {source} ({status})")

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
            tool_definitions = []
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

                # Collect tool definitions (name + description + parameters)
                # so the model knows how to call each declared tool
                if skill.tools:
                    all_mcp_tools = await mcp_client_pool.get_all_tools()
                    for tool_name in skill.tools:
                        if tool_name in self._local_tools:
                            td = self._local_tools[tool_name]
                            tool_definitions.append({
                                "name": tool_name,
                                "description": td.description,
                                "parameters": td.input_schema,
                                "source": "local"
                            })
                        elif tool_name in all_mcp_tools:
                            info = all_mcp_tools[tool_name]
                            tool_definitions.append({
                                "name": tool_name,
                                "description": info.get("description", ""),
                                "parameters": info.get("input_schema", {}),
                                "source": "mcp",
                                "server_name": info.get("server_name", "")
                            })

            return {
                "skill_name": skill_name,
                "content": content,
                "has_entrypoint": has_entrypoint,
                "tool_definitions": tool_definitions,
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

            # Check if skill has an entrypoint before executing
            registry = get_skill_registry()
            skill = registry.get_skill(skill_name)
            if skill:
                has_entrypoint = False
                if skill.entrypoint and __import__('pathlib').Path(skill.entrypoint).exists():
                    has_entrypoint = True
                elif skill.dir_path:
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
                if not has_entrypoint:
                    # Prompt-only skill: no script to execute
                    # Return a clear message so the model knows to use declared tools directly
                    declared_tools = skill.tools or []
                    tool_hint = ""
                    if declared_tools:
                        tool_hint = f" This skill declares the following tools that you can call directly: {', '.join(declared_tools)}. Call them directly instead of execute_skill."
                    return {
                        "status": "error",
                        "skill_name": skill_name,
                        "error": f"Skill '{skill_name}' is a prompt-only skill with no executable script. Its instructions have already been loaded into your context via load_skill. Follow the skill's instructions to complete the task.{tool_hint}",
                        "execution_time_ms": 0,
                        "logs": []
                    }

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

        # 1. 添加本地工具（排除未安装的）
        for tool_name, tool_def in self._local_tools.items():
            if not tool_def.installed:
                continue
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
                        server_id=tool_server_id
                    )

        # 3. 按白名单过滤（混合模式）
        # allowed_tools=None     → 不过滤，加载已绑定server的全部tool（兼容旧行为）
        # allowed_tools=[]       → 用户明确不需要工具，返回空（不注入skill工具）
        # allowed_tools=["xx"]   → 混合逻辑：白名单中的 tool 放行 + skill工具；
        #   对每个已绑定 server，如果没有任何 tool 被选中，则该 server 全部 tool 放行
        if allowed_tools is not None and isinstance(allowed_tools, list):
            # Empty list = user explicitly wants NO tools
            if len(allowed_tools) == 0:
                return {}

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

    async def get_mcp_server_ids_for_tools(self, tool_names: List[str]) -> List[str]:
        """Find MCP server IDs that provide the given tools (by original name).

        Since tools are now identified by original_name (no prefix),
        we simply look up each tool name in each server's tool list.
        """
        server_ids = set()
        async with mcp_client_pool.lock:
            for tool_name in tool_names:
                for server_id, connection in mcp_client_pool.connections.items():
                    from app.services.mcp_pool import ConnectionStatus
                    if connection.config.status != ConnectionStatus.CONNECTED:
                        continue
                    if tool_name in connection.tools:
                        server_ids.add(server_id)
                        logger.info(f"  Tool '{tool_name}' found on server '{connection.config.name}' (id={server_id})")
                        break

        if not server_ids and tool_names:
            logger.warning(f"No MCP servers found for tools: {tool_names}")
        return list(server_ids)

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
        # 1. Check local tools
        if tool_name in self._local_tools:
            tool_def = self._local_tools[tool_name]
            if not tool_def.installed:
                return {"error": f"工具 '{tool_name}' 依赖未安装，请先在工具管理中安装依赖"}
            if tool_def.handler:
                logger.info(f"Calling local tool: {tool_name}")
                return await tool_def.handler(**arguments)

        # 2. Try MCP tools via pool (uses original_name, no prefix)
        try:
            logger.info(f"Calling MCP tool: {tool_name}")
            return await mcp_client_pool.call_tool(tool_name, arguments)
        except ValueError:
            raise ValueError(f"Tool '{tool_name}' not found")
        except Exception as e:
            raise ValueError(f"Tool '{tool_name}' failed: {e}")

    # ===== Plugin Management =====

    def get_tool_plugins(self) -> List[Dict[str, Any]]:
        """Get all tool plugins with install status, grouped by service.

        Returns:
            List of plugin info dicts, each with:
            - service_name, service_description, installed, deps, tools[]
        """
        # Group tools by service_name
        services: Dict[str, Dict[str, Any]] = {}
        for tool_name, tool_def in self._local_tools.items():
            svc_name = tool_def.service_name or tool_def.source
            if svc_name not in services:
                # Try to get service_description from the tool's source class
                svc_desc = ""
                if tool_def.source == "local":
                    # Look up the service class to get description
                    from app.tools.plugin_registry import get_service_descriptors
                    descriptors = get_service_descriptors()
                    for dname, desc in descriptors.items():
                        cls_svc_name = getattr(desc.service_cls, 'service_name', dname)
                        if cls_svc_name == svc_name or dname == svc_name:
                            svc_desc = getattr(desc.service_cls, 'service_description', '')
                            break

                services[svc_name] = {
                    "service_name": svc_name,
                    "service_description": svc_desc,
                    "installed": True,
                    "deps": [],
                    "tools": []
                }
            services[svc_name]["tools"].append({
                "name": tool_def.name,
                "description": tool_def.description,
                "installed": tool_def.installed,
            })
            # If any tool in service is not installed, the service is not installed
            if not tool_def.installed:
                services[svc_name]["installed"] = False
            if tool_def.deps:
                services[svc_name]["deps"] = tool_def.deps

        return list(services.values())

    def get_uninstalled_services(self) -> Dict[str, Dict[str, Any]]:
        """Get services that have unmet dependencies.

        Returns:
            Dict mapping service_name to {deps, missing}
        """
        result = {}
        for plugin in self.get_tool_plugins():
            if not plugin["installed"]:
                # Check which deps are actually missing
                from app.tools.base import BaseToolService
                missing = []
                for dep in plugin["deps"]:
                    try:
                        importlib.import_module(dep)
                    except ImportError:
                        missing.append(dep)
                if missing:
                    result[plugin["service_name"]] = {
                        "deps": plugin["deps"],
                        "missing": missing
                    }
        return result

    # Install tracking
    _install_tasks: Dict[str, Any] = {}  # service_name -> {"status", "output", "error"}

    async def install_service_deps(self, service_name: str) -> Dict[str, Any]:
        """Install pip dependencies for a tool service.

        Args:
            service_name: The service_name to install deps for

        Returns:
            Dict with success status
        """
        # Find the service's deps
        plugin = None
        for p in self.get_tool_plugins():
            if p["service_name"] == service_name:
                plugin = p
                break

        if not plugin:
            return {"success": False, "error": f"Service '{service_name}' not found"}

        if not plugin["deps"]:
            return {"success": False, "error": f"Service '{service_name}' has no dependencies to install"}

        if plugin["installed"]:
            return {"success": True, "message": "Already installed"}

        # Check if install already in progress
        if service_name in self._install_tasks and self._install_tasks[service_name]["status"] == "installing":
            return {"success": False, "error": "Installation already in progress"}

        deps = plugin["deps"]
        self._install_tasks[service_name] = {"status": "installing", "output": "", "error": ""}

        try:
            import subprocess
            import sys
            pip_cmd = [sys.executable, "-m", "pip", "install"] + deps
            logger.info(f"Installing deps for {service_name}: {deps}")

            proc = await asyncio.create_subprocess_exec(
                *pip_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
            output = stdout.decode("utf-8", errors="replace")

            if proc.returncode == 0:
                self._install_tasks[service_name] = {
                    "status": "installed",
                    "output": output[-500:],
                    "error": ""
                }
                # Re-register tools for this service
                await self._reregister_service(service_name)
                return {"success": True, "message": f"Successfully installed {deps}", "output": output[-500:]}
            else:
                self._install_tasks[service_name] = {
                    "status": "failed",
                    "output": output[-500:],
                    "error": f"pip install exited with code {proc.returncode}"
                }
                return {"success": False, "error": f"Installation failed (exit code {proc.returncode})", "output": output[-500:]}

        except asyncio.TimeoutError:
            self._install_tasks[service_name] = {
                "status": "failed",
                "output": "",
                "error": "Installation timed out (5 min)"
            }
            return {"success": False, "error": "Installation timed out"}
        except Exception as e:
            self._install_tasks[service_name] = {
                "status": "failed",
                "output": "",
                "error": str(e)
            }
            return {"success": False, "error": str(e)}

    def get_install_status(self, service_name: str) -> Optional[Dict[str, Any]]:
        """Get install status for a service"""
        return self._install_tasks.get(service_name)

    async def _reregister_service(self, service_name: str):
        """Re-register tools for a service after its deps are installed.

        This triggers the service to re-provide its tools with handlers.
        """
        # Import the service registry from main.py context
        from app.tools.plugin_registry import reregister_service
        await reregister_service(service_name, self)


# 全局单例
_tool_manager: Optional[UnifiedToolManager] = None


def get_tool_manager() -> UnifiedToolManager:
    """获取全局统一工具管理器"""
    global _tool_manager
    if _tool_manager is None:
        _tool_manager = UnifiedToolManager()
        _tool_manager.register_skill_tools()
    return _tool_manager
