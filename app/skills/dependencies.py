"""
Skill 依赖管理

实现 requirements 安装、版本兼容性检查、隔离环境
"""
import asyncio
import importlib.metadata
import logging
import sys
from datetime import datetime
from app.utils.timezone import beijing_now
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app.models.skill import Skill

logger = logging.getLogger(__name__)


# ============================================
# 数据模型
# ============================================

class SkillDependency(BaseModel):
    """Skill 依赖"""
    name: str = Field(..., description="包名")
    version_spec: Optional[str] = Field(default=None, description="版本规格, e.g., '>=1.0.0,<2.0.0'")
    required: bool = Field(default=True, description="是否必需")


class SkillEnvironment(BaseModel):
    """Skill 环境"""
    skill_id: str = Field(..., description="Skill ID")
    env_path: str = Field(..., description="环境路径")
    dependencies: List[SkillDependency] = Field(default_factory=list, description="依赖列表")
    created_at: datetime = Field(default_factory=beijing_now)
    last_used: datetime = Field(default_factory=beijing_now)


# ============================================
# 依赖管理器
# ============================================

class DependencyManager:
    """Skill 依赖管理器"""

    def __init__(self, base_env_path: str = None):
        self.base_env_path = (
            Path(base_env_path) if base_env_path
            else Path.home() / ".quest3" / "envs"
        )
        self.base_env_path.mkdir(parents=True, exist_ok=True)
        self._environments: Dict[str, SkillEnvironment] = {}

    async def install_dependencies(
        self,
        skill: Skill,
        isolate: bool = False,
    ) -> Tuple[bool, List[str]]:
        """
        安装 Skill 依赖

        Args:
            skill: Skill 对象
            isolate: 是否使用隔离环境

        Returns:
            (是否成功, 问题列表)
        """
        if not skill.requirements:
            logger.debug(f"No dependencies for skill: {skill.name}")
            return True, []

        logger.info(
            f"Installing dependencies for {skill.name}: {skill.requirements}"
        )

        if isolate:
            return await self._install_isolated(skill)
        else:
            return await self._install_global(skill)

    async def _install_global(self, skill: Skill) -> Tuple[bool, List[str]]:
        """全局安装依赖"""
        issues = []

        for req_str in skill.requirements:
            try:
                logger.info(f"Installing: {req_str}")
                await self._pip_install(req_str)
                logger.info(f"Installed: {req_str}")
            except Exception as e:
                error = str(e)
                logger.error(f"Failed to install {req_str}: {error}")
                issues.append(f"{req_str}: {error}")

        return len(issues) == 0, issues

    async def _install_isolated(self, skill: Skill) -> Tuple[bool, List[str]]:
        """在隔离环境中安装"""
        env_path = self.base_env_path / self._sanitize_name(skill.name)
        issues = []

        # 创建虚拟环境（如果不存在）
        if not env_path.exists():
            try:
                await self._create_virtualenv(env_path)
            except Exception as e:
                logger.error(f"Failed to create virtualenv: {e}")
                return False, [f"Failed to create virtualenv: {e}"]

        # 获取 pip 路径
        if sys.platform == "win32":
            pip_path = env_path / "Scripts" / "pip.exe"
        else:
            pip_path = env_path / "bin" / "pip"

        if not pip_path.exists():
            return False, [f"pip not found at {pip_path}"]

        # 安装依赖
        for req_str in skill.requirements:
            try:
                logger.info(f"Installing (isolated): {req_str}")
                await self._pip_install(req_str, pip_path=str(pip_path))
                logger.info(f"Installed (isolated): {req_str}")
            except Exception as e:
                error = str(e)
                logger.error(f"Failed to install {req_str} in isolated env: {error}")
                issues.append(f"{req_str}: {error}")

        # 保存环境信息
        dependencies = [
            self._parse_requirement(req_str)
            for req_str in skill.requirements
        ]

        self._environments[skill.id] = SkillEnvironment(
            skill_id=skill.id,
            env_path=str(env_path),
            dependencies=dependencies,
            created_at=beijing_now(),
            last_used=beijing_now(),
        )

        return len(issues) == 0, issues

    async def _create_virtualenv(self, env_path: Path) -> None:
        """创建虚拟环境"""
        logger.info(f"Creating virtualenv at {env_path}")

        import venv

        # 创建虚拟环境
        venv.create(env_path, with_pip=True)

        # 确定 pip 路径
        if sys.platform == "win32":
            pip_path = env_path / "Scripts" / "pip.exe"
        else:
            pip_path = env_path / "bin" / "pip"

        # 升级 pip
        logger.info("Upgrading pip")
        await self._pip_install("--upgrade pip", pip_path=str(pip_path))

    async def _pip_install(self, requirement: str, pip_path: str = "pip") -> None:
        """执行 pip install"""
        cmd = [pip_path, "install", requirement]

        logger.debug(f"Running command: {' '.join(cmd)}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error = stderr.decode() if stderr else "Unknown error"
            if stdout:
                error = f"{stdout.decode()}\n{error}"
            raise RuntimeError(f"pip install failed: {error}")

        if stdout:
            logger.debug(stdout.decode())

    async def check_compatibility(
        self,
        skill: Skill,
    ) -> Tuple[bool, List[str]]:
        """
        检查依赖兼容性

        Returns:
            (是否兼容, 问题列表)
        """
        issues = []

        if not skill.requirements:
            return True, []

        for req_str in skill.requirements:
            req = self._parse_requirement(req_str)

            try:
                installed = importlib.metadata.version(req.name)

                if req.version_spec:
                    if not self._version_match(installed, req.version_spec):
                        issues.append(
                            f"{req.name}: installed {installed}, "
                            f"requires {req.version_spec}"
                        )
                else:
                    logger.debug(f"{req.name} {installed} is installed")

            except importlib.metadata.PackageNotFoundError:
                issues.append(f"{req.name}: not installed")

        return len(issues) == 0, issues

    def _parse_requirement(self, req_str: str) -> SkillDependency:
        """解析 requirement 字符串"""
        # 简单解析
        import re

        # 匹配 name 和 version spec
        match = re.match(r"([a-zA-Z0-9_-]+)(.*)", req_str.strip())
        if match:
            name = match.group(1)
            version_spec = match.group(2).strip() if match.group(2) else None
            return SkillDependency(name=name, version_spec=version_spec)

        return SkillDependency(name=req_str.strip())

    def _version_match(self, version: str, spec: str) -> bool:
        """检查版本匹配"""
        try:
            from packaging import version as pkg_version
            from packaging.specifiers import SpecifierSet

            ver = pkg_version.parse(version)
            spec_set = SpecifierSet(spec)
            return ver in spec_set
        except ImportError:
            # 如果没有 packaging 库，做简单检查
            logger.warning("'packaging' library not found, skipping version check")
            return True
        except Exception as e:
            logger.warning(f"Version check failed: {e}")
            return False

    def get_environment(self, skill_id: str) -> Optional[SkillEnvironment]:
        """获取 Skill 的环境"""
        return self._environments.get(skill_id)

    def list_environments(self) -> List[SkillEnvironment]:
        """列出所有环境"""
        return list(self._environments.values())

    def remove_environment(self, skill_id: str) -> bool:
        """移除 Skill 的环境"""
        env = self._environments.pop(skill_id, None)
        if env:
            # 清理目录
            try:
                import shutil
                shutil.rmtree(env.env_path, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Failed to remove environment dir: {e}")
            return True
        return False

    async def ensure_packaging_library(self) -> bool:
        """确保 packaging 库可用（用于版本检查）"""
        try:
            import packaging
            return True
        except ImportError:
            try:
                await self._pip_install("packaging")
                return True
            except Exception:
                return False

    def _sanitize_name(self, name: str) -> str:
        """清理名称以用于路径"""
        import re
        return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


# ============================================
# 全局实例
# ============================================

_dependency_manager: Optional[DependencyManager] = None


def get_dependency_manager() -> DependencyManager:
    """获取或创建全局 DependencyManager"""
    global _dependency_manager
    if _dependency_manager is None:
        _dependency_manager = DependencyManager()
    return _dependency_manager
