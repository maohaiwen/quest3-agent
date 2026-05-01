"""
Skill module for the agent system

包含：
- loader: Skill 加载器
- registry: Skill 注册表
- executor: Skill 执行引擎
- trigger: Skill 触发机制
- dependencies: Skill 依赖管理
- github_importer: GitHub 技能导入
"""
from app.skills.loader import SkillLoader
from app.skills.registry import SkillRegistry, get_skill_registry
from app.skills.executor import (
    SkillExecutor,
    SkillExecutionContext,
    SkillExecutionResult,
    SkillContextManager,
    PromptRunner,
    ScriptRunner,
    get_skill_executor,
)
from app.skills.trigger import (
    SkillTriggerManager,
    SkillTrigger,
    TriggerType,
    KeywordTriggerConfig,
    RegexTriggerConfig,
    IntentTriggerConfig,
    get_trigger_manager,
)
from app.skills.dependencies import (
    DependencyManager,
    SkillDependency,
    SkillEnvironment,
    get_dependency_manager,
)
from app.skills.github_importer import (
    GitHubSkillImporter,
    GitHubRepoRef,
    get_github_importer,
)

__all__ = [
    # Loader & Registry
    "SkillLoader",
    "SkillRegistry",
    "get_skill_registry",
    # Executor
    "SkillExecutor",
    "SkillExecutionContext",
    "SkillExecutionResult",
    "SkillContextManager",
    "PromptRunner",
    "ScriptRunner",
    "get_skill_executor",
    # Trigger
    "SkillTriggerManager",
    "SkillTrigger",
    "TriggerType",
    "KeywordTriggerConfig",
    "RegexTriggerConfig",
    "IntentTriggerConfig",
    "get_trigger_manager",
    # Dependencies
    "DependencyManager",
    "SkillDependency",
    "SkillEnvironment",
    "get_dependency_manager",
    # GitHub
    "GitHubSkillImporter",
    "GitHubRepoRef",
    "get_github_importer",
]
