"""
Skill 执行引擎

实现 SkillExecutor、PromptRunner、ScriptRunner、ContextManager
"""
import asyncio
import importlib.util
import inspect
import json
import logging
import sys
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from app.utils.timezone import beijing_now
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app.models.skill import Skill
from app.skills.registry import SkillRegistry, get_skill_registry

logger = logging.getLogger(__name__)


# ============================================
# 数据模型
# ============================================

class SkillExecutionContext(BaseModel):
    """Skill 执行上下文

    支持属性访问 (context.input_data) 和字典式访问 (context["input_data"])，
    确保 LLM 生成的脚本无论用哪种风格都能正确执行。
    """
    session_id: str = Field(..., description="会话 ID")
    skill_id: str = Field(..., description="Skill ID")
    skill_name: str = Field(..., description="Skill 名称")
    input_data: Dict[str, Any] = Field(default_factory=dict, description="输入数据")
    config: Dict[str, Any] = Field(default_factory=dict, description="Skill 配置")
    state: Dict[str, Any] = Field(default_factory=dict, description="执行状态（可写）")
    tools: List[str] = Field(default_factory=list, description="可用工具")
    created_at: datetime = Field(default_factory=beijing_now)

    def __getitem__(self, key: str) -> Any:
        """Support dict-style access: context["input_data"]"""
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        """Support 'input_data' in context"""
        return hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        """Support context.get("input_data", {})"""
        return getattr(self, key, default)


class SkillExecutionResult(BaseModel):
    """Skill 执行结果"""
    success: bool = Field(..., description="是否成功")
    output: Any = Field(default=None, description="输出数据")
    error: Optional[str] = Field(default=None, description="错误信息")
    execution_time_ms: float = Field(default=0.0, description="执行时间（毫秒）")
    state_updates: Dict[str, Any] = Field(default_factory=dict, description="状态更新")
    logs: List[str] = Field(default_factory=list, description="执行日志")



# ============================================
# Skill Runner 基类
# ============================================

class SkillRunner(ABC):
    """Skill Runner 基类"""

    @abstractmethod
    async def run(
        self,
        skill: Skill,
        context: SkillExecutionContext,
    ) -> SkillExecutionResult:
        """执行 Skill"""
        pass


class PromptRunner(SkillRunner):
    """纯提示词模式 Runner"""

    async def run(
        self,
        skill: Skill,
        context: SkillExecutionContext,
    ) -> SkillExecutionResult:
        """
        纯提示词模式执行：
        1. 将 skill.md 内容注入到系统提示词
        2. 返回增强后的提示词
        """
        start_time = time.time()
        logs = ["Starting prompt-based skill execution"]

        try:
            # 构建增强提示词
            enhanced_prompt = self._build_enhanced_prompt(skill, context)
            logs.append("Built enhanced prompt successfully")

            return SkillExecutionResult(
                success=True,
                output={
                    "type": "prompt_injection",
                    "prompt_content": skill.skill_content,
                    "enhanced_prompt": enhanced_prompt,
                },
                error=None,
                execution_time_ms=(time.time() - start_time) * 1000,
                state_updates={},
                logs=logs,
            )
        except Exception as e:
            logger.exception(f"Error in PromptRunner: {e}")
            logs.append(f"Error: {e}")
            return SkillExecutionResult(
                success=False,
                output=None,
                error=str(e),
                execution_time_ms=(time.time() - start_time) * 1000,
                state_updates={},
                logs=logs,
            )

    def _build_enhanced_prompt(
        self,
        skill: Skill,
        context: SkillExecutionContext,
    ) -> str:
        """构建增强提示词"""
        # 将输入数据注入到提示词
        input_str = json.dumps(context.input_data, ensure_ascii=False, indent=2)

        return f"""{skill.skill_content}

【当前上下文】
输入数据:
{input_str}

请根据以上技能说明处理用户请求。
"""


class ScriptRunner(SkillRunner):
    """Python 脚本模式 Runner"""

    async def run(
        self,
        skill: Skill,
        context: SkillExecutionContext,
    ) -> SkillExecutionResult:
        """
        Python 脚本模式执行：
        1. 动态加载 main.py 或执行 shell/batch 脚本
        2. 调用约定的入口函数
        3. 捕获输出和错误
        """
        start_time = time.time()
        logs = []

        try:
            if not skill.entrypoint:
                raise ValueError("Skill has no entrypoint defined")

            entry_path = Path(skill.entrypoint)
            if not entry_path.exists():
                raise FileNotFoundError(f"Entrypoint not found: {skill.entrypoint}")

            # 根据文件类型选择执行方式
            if entry_path.suffix in ['.sh']:
                # Shell脚本 (Unix/Linux/macOS)
                return await self._run_shell_script(entry_path, context, start_time, logs)
            elif entry_path.suffix in ['.ps1']:
                # PowerShell脚本 (Windows)
                return await self._run_powershell_script(entry_path, context, start_time, logs)
            else:
                # Python模块
                return await self._run_python_module(skill, context, start_time, logs)

        except Exception as e:
            logger.exception(f"Error in ScriptRunner: {e}")
            logs.append(f"Error: {e}")
            return SkillExecutionResult(
                success=False,
                output=None,
                error=str(e),
                execution_time_ms=(time.time() - start_time) * 1000,
                state_updates={},
                logs=logs,
            )

    async def _run_python_module(
        self,
        skill: Skill,
        context: SkillExecutionContext,
        start_time: float,
        logs: List[str]
    ) -> SkillExecutionResult:
        """执行 Python 模块"""
        logs.append(f"Loading Python module from {skill.entrypoint}")
        module = await self._load_module(skill)
        logs.append("Module loaded successfully")

        func = self._find_entry_function(module)
        if not func:
            raise ValueError("Skill module has no 'execute' or 'call' function")
        logs.append(f"Found entry function: {func.__name__}")

        if inspect.iscoroutinefunction(func):
            result = await func(context)
        else:
            result = await asyncio.to_thread(func, context)

        logs.append("Execution completed successfully")

        if isinstance(result, SkillExecutionResult):
            result.logs = logs + result.logs
            result.execution_time_ms = (time.time() - start_time) * 1000
            return result

        state_updates = {}
        if hasattr(result, "state_updates"):
            state_updates = result.state_updates
        elif hasattr(context, "state") and context.state:
            state_updates = context.state.copy()

        return SkillExecutionResult(
            success=True,
            output=result,
            error=None,
            execution_time_ms=(time.time() - start_time) * 1000,
            state_updates=state_updates,
            logs=logs,
        )

    async def _run_shell_script(
        self,
        script_path: Path,
        context: SkillExecutionContext,
        start_time: float,
        logs: List[str]
    ) -> SkillExecutionResult:
        """执行 Shell 脚本

        使用 subprocess.run + asyncio.to_thread 来执行，
        避免 asyncio.create_subprocess_exec 对中文路径的编码问题。
        """
        import subprocess
        import os

        logs.append(f"Running shell script: {script_path}")

        # 准备环境变量（继承当前进程环境）
        env = os.environ.copy()
        env["INPUT_DATA"] = json.dumps(context.input_data or {}, ensure_ascii=False)
        env["SKILL_NAME"] = context.skill_name
        env["SESSION_ID"] = context.session_id

        def _run_sync():
            """同步执行 shell 脚本，在 to_thread 中调用"""
            return subprocess.run(
                ["bash", str(script_path)],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        try:
            proc = await asyncio.to_thread(_run_sync)

            output = proc.stdout.decode('utf-8', errors='replace') if proc.stdout else ""
            error = proc.stderr.decode('utf-8', errors='replace') if proc.stderr else ""

            logs.append(f"Script exit code: {proc.returncode}")
            if output:
                logs.append(f"Output: {output[:500]}")
            if error:
                logs.append(f"Error: {error[:500]}")

            # 尝试解析输出为JSON
            try:
                output_data = json.loads(output) if output else {}
            except (json.JSONDecodeError, TypeError):
                output_data = {"output": output, "raw": True}

            return SkillExecutionResult(
                success=proc.returncode == 0,
                output=output_data,
                error=error if proc.returncode != 0 else None,
                execution_time_ms=(time.time() - start_time) * 1000,
                state_updates={},
                logs=logs,
            )

        except Exception as e:
            error_msg = repr(e)
            logs.append(f"Shell script execution failed: {error_msg}")
            return SkillExecutionResult(
                success=False,
                output=None,
                error=error_msg,
                execution_time_ms=(time.time() - start_time) * 1000,
                state_updates={},
                logs=logs,
            )

    async def _run_powershell_script(
        self,
        script_path: Path,
        context: SkillExecutionContext,
        start_time: float,
        logs: List[str]
    ) -> SkillExecutionResult:
        """执行 PowerShell 脚本

        PowerShell 脚本是 Windows 技能的首选方式：
        - 原生支持 JSON 解析 (ConvertFrom-Json)
        - 原生 UTF-8 支持，无编码问题
        - 无 cmd.exe 转义冲突
        - 可通过 $env:INPUT_DATA 读取输入
        """
        import subprocess
        import os

        logs.append(f"Running PowerShell script: {script_path}")

        # 准备环境变量（继承当前进程环境）
        env = os.environ.copy()
        env["INPUT_DATA"] = json.dumps(context.input_data or {}, ensure_ascii=False)
        env["SKILL_NAME"] = context.skill_name
        env["SESSION_ID"] = context.session_id

        def _run_sync():
            """同步执行 PowerShell 脚本"""
            return subprocess.run(
                [
                    "powershell", "-ExecutionPolicy", "Bypass",
                    "-File", str(script_path),
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        try:
            proc = await asyncio.to_thread(_run_sync)

            output = proc.stdout.decode('utf-8', errors='replace') if proc.stdout else ""
            error = proc.stderr.decode('utf-8', errors='replace') if proc.stderr else ""

            logs.append(f"Script exit code: {proc.returncode}")
            if output:
                logs.append(f"Output: {output[:500]}")
            if error:
                logs.append(f"Error: {error[:500]}")

            # 尝试解析输出为JSON
            try:
                output_data = json.loads(output) if output else {}
            except (json.JSONDecodeError, TypeError):
                output_data = {"output": output, "raw": True}

            return SkillExecutionResult(
                success=proc.returncode == 0,
                output=output_data,
                error=error if proc.returncode != 0 else None,
                execution_time_ms=(time.time() - start_time) * 1000,
                state_updates={},
                logs=logs,
            )

        except Exception as e:
            error_msg = repr(e)
            logs.append(f"PowerShell script execution failed: {error_msg}")
            return SkillExecutionResult(
                success=False,
                output=None,
                error=error_msg,
                execution_time_ms=(time.time() - start_time) * 1000,
                state_updates={},
                logs=logs,
            )

    async def _load_module(self, skill: Skill) -> ModuleType:
        """动态加载 Skill 模块"""
        if not skill.entrypoint:
            raise ValueError("Skill has no entrypoint")

        entry_path = Path(skill.entrypoint)
        if not entry_path.exists():
            raise FileNotFoundError(f"Entrypoint not found: {skill.entrypoint}")

        # 动态导入
        module_name = f"skill_{skill.name.replace('-', '_').replace('.', '_')}"

        # 清除旧模块（如果存在）
        if module_name in sys.modules:
            del sys.modules[module_name]

        spec = importlib.util.spec_from_file_location(module_name, str(entry_path))
        if not spec or not spec.loader:
            raise ImportError(f"Cannot load module from {entry_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        return module

    def _find_entry_function(self, module: ModuleType) -> Optional[callable]:
        """查找入口函数"""
        # 优先找 execute
        if hasattr(module, "execute"):
            return module.execute
        # 兼容旧版本的 call
        if hasattr(module, "call"):
            return module.call
        return None


# ============================================
# Skill 上下文管理器
# ============================================

class SkillContextManager:
    """Skill 上下文管理器"""

    def __init__(self):
        self._contexts: Dict[str, SkillExecutionContext] = {}  # execution_id -> context
        self._states: Dict[str, Dict[str, Any]] = {}  # session_id -> global state

    def create_context(
        self,
        session_id: str,
        skill_name: str,
        input_data: Dict[str, Any] = None,
        config: Dict[str, Any] = None,
        skill_id: str = None,
    ) -> Tuple[str, SkillExecutionContext]:
        """
        创建执行上下文

        Returns:
            (execution_id, context)
        """
        execution_id = str(uuid.uuid4())

        # 获取或创建会话级状态
        if session_id not in self._states:
            self._states[session_id] = {}

        context = SkillExecutionContext(
            session_id=session_id,
            skill_id=skill_id or f"skill_{skill_name}",
            skill_name=skill_name,
            input_data=input_data or {},
            config=config or {},
            state=self._states[session_id],
            tools=[],
            created_at=beijing_now(),
        )

        self._contexts[execution_id] = context
        return execution_id, context

    def get_context(self, execution_id: str) -> Optional[SkillExecutionContext]:
        """获取上下文"""
        return self._contexts.get(execution_id)

    def update_state(
        self,
        session_id: str,
        state_updates: Dict[str, Any],
    ) -> None:
        """更新会话状态"""
        if session_id not in self._states:
            self._states[session_id] = {}
        self._states[session_id].update(state_updates)

    def get_session_state(self, session_id: str) -> Dict[str, Any]:
        """获取会话状态"""
        return self._states.get(session_id, {}).copy()

    def clear_session(self, session_id: str) -> None:
        """清理会话"""
        if session_id in self._states:
            del self._states[session_id]
        # 同时清理相关的执行上下文
        to_remove = [
            eid for eid, ctx in self._contexts.items()
            if ctx.session_id == session_id
        ]
        for eid in to_remove:
            del self._contexts[eid]


# ============================================
# Skill 执行器
# ============================================

class SkillExecutor:
    """Skill 执行器"""

    def __init__(self, skill_registry: SkillRegistry = None):
        self.registry = skill_registry or get_skill_registry()
        self.context_manager = SkillContextManager()
        self.runners = {
            "prompt": PromptRunner(),
            "script": ScriptRunner(),
        }
        # 确保 registry 初始化
        if not self.registry._loaded:
            self.registry.initialize()

    async def execute(
        self,
        skill_name: str,
        input_data: Dict[str, Any] = None,
        config: Dict[str, Any] = None,
        session_id: str = None,
    ) -> SkillExecutionResult:
        """
        执行 Skill

        Args:
            skill_name: Skill 名称
            input_data: 输入数据
            config: Skill 配置
            session_id: 会话 ID（用于状态保持）

        Returns:
            SkillExecutionResult
        """
        # 生成会话 ID（如果没有）
        if not session_id:
            session_id = f"session_{uuid.uuid4().hex[:8]}"

        # 获取 Skill
        skill = self.registry.get_skill(skill_name)
        if not skill:
            logger.warning(f"Skill not found: {skill_name}")
            return SkillExecutionResult(
                success=False,
                output=None,
                error=f"Skill not found: {skill_name}",
                execution_time_ms=0,
                state_updates={},
                logs=[f"Skill not found: {skill_name}"],
            )

        if not skill.enabled:
            logger.warning(f"Skill is disabled: {skill_name}")
            return SkillExecutionResult(
                success=False,
                output=None,
                error=f"Skill is disabled: {skill_name}",
                execution_time_ms=0,
                state_updates={},
                logs=[f"Skill is disabled: {skill_name}"],
            )

        # 创建上下文
        execution_id, context = self.context_manager.create_context(
            session_id=session_id,
            skill_name=skill_name,
            input_data=input_data,
            config=config,
            skill_id=skill.id,
        )

        logger.info(f"Executing skill: {skill_name} (session: {session_id})")

        # 选择 runner
        runner = self._get_runner(skill)

        # 执行
        result = await runner.run(skill, context)

        # 更新状态
        if result.success and result.state_updates:
            self.context_manager.update_state(session_id, result.state_updates)

        logger.info(
            f"Skill execution completed: {skill_name}, "
            f"success: {result.success}, "
            f"time: {result.execution_time_ms:.2f}ms"
        )

        return result

    def _get_runner(self, skill: Skill) -> SkillRunner:
        """根据 skill 类型选择 runner"""
        if skill.entrypoint and Path(skill.entrypoint).exists():
            return self.runners["script"]
        # Fallback: try to find any executable script in skill directory
        if skill.dir_path:
            dir_path = Path(skill.dir_path)
            is_windows = sys.platform == "win32"
            candidates = (
                ["main.py", "main.ps1", "main.sh"]
                if is_windows
                else ["main.py", "main.sh", "main.ps1"]
            )
            for name in candidates:
                candidate = dir_path / name
                if candidate.exists():
                    logger.warning(
                        f"Skill '{skill.name}' entrypoint '{skill.entrypoint}' not found, "
                        f"falling back to '{candidate}'"
                    )
                    # Fix the entrypoint so ScriptRunner can use it
                    skill.entrypoint = str(candidate.resolve())
                    return self.runners["script"]
        logger.warning(
            f"Skill '{skill.name}' has no executable entrypoint, falling back to PromptRunner"
        )
        return self.runners["prompt"]

    def get_session_state(self, session_id: str) -> Dict[str, Any]:
        """获取会话状态"""
        return self.context_manager.get_session_state(session_id)

    def clear_session(self, session_id: str) -> None:
        """清理会话"""
        self.context_manager.clear_session(session_id)


# ============================================
# 全局实例
# ============================================

_executor: Optional[SkillExecutor] = None


def get_skill_executor() -> SkillExecutor:
    """获取或创建全局 SkillExecutor"""
    global _executor
    if _executor is None:
        _executor = SkillExecutor()
    return _executor
