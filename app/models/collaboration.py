"""Collaboration models for multi-agent collaboration framework"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class CollaborationMode(str, Enum):
    """Collaboration mode"""
    SUPERVISOR = "supervisor"
    PIPELINE = "pipeline"
    VOTING = "voting"
    ADVERSARIAL_GEN_DIS = "adversarial_generate_discriminate"
    ADVERSARIAL_GAME = "adversarial_game"


class CollaborationAgentRole(str, Enum):
    """Agent role in collaboration"""
    # Supervisor mode
    SUPERVISOR = "supervisor"
    CHILD = "child"
    # Pipeline mode
    WORKER = "worker"
    # Voting mode
    VOTER = "voter"
    AGGREGATOR = "aggregator"
    # Adversarial generate-discriminate mode
    GENERATOR = "generator"
    DISCRIMINATOR = "discriminator"
    JUDGE = "judge"
    # Adversarial game mode
    REFEREE = "referee"
    PARTICIPANT = "participant"
    # Legacy roles (kept for backwards compatibility)
    PLAYER_BLACK = "player_black"
    PLAYER_WHITE = "player_white"


class CollaborationAgentConfig(BaseModel):
    """Agent configuration in a collaboration"""
    agent_id: str = Field(..., description="Agent ID (references agents table)")
    role: str = Field(..., description="Agent role in this collaboration")
    priority: int = Field(default=0, description="Execution priority")
    config_json: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Role-specific config")


class SupervisorConfig(BaseModel):
    """Configuration for supervisor mode"""
    split_prompt: Optional[str] = Field(
        default=None,
        description="Prompt template for task splitting (uses default if not provided)"
    )
    parallel_execution: bool = Field(default=True, description="Execute child agents in parallel")
    summary_prompt: Optional[str] = Field(
        default=None,
        description="Prompt template for summarizing results"
    )


class AdversarialGenDisConfig(BaseModel):
    """Configuration for generate-discriminate adversarial mode"""
    max_rounds: int = Field(default=3, description="Maximum adversarial rounds")
    judge_enabled: bool = Field(default=False, description="Whether to use a judge agent")
    termination_on_pass: bool = Field(default=True, description="Stop when discriminator passes")


class AdversarialGameConfig(BaseModel):
    """Configuration for adversarial game mode"""
    turn_strategy: str = Field(
        default="simultaneous",
        description="Turn strategy: 'simultaneous' (all act at once, e.g. rock-paper-scissors) or 'turn_based' (take turns, e.g. chess)"
    )
    max_rounds: int = Field(default=10, description="Maximum game rounds")
    game_rules: str = Field(
        default="",
        description="Game rules description, used to build prompts for participants and referee"
    )
    participant_order: List[str] = Field(
        default_factory=list,
        description="Order of participants for turn_based strategy (role identifiers)"
    )
    shared_state: Dict[str, Any] = Field(
        default_factory=dict,
        description="Shared state accessible to all agents"
    )
    referee_enabled: bool = Field(
        default=True,
        description="Whether to use a referee agent to judge rounds and determine winner"
    )
    referee_prompt: Optional[str] = Field(
        default=None,
        description="Custom prompt template for referee (uses default if not provided)"
    )
    round_input_template: Optional[str] = Field(
        default=None,
        description="[Legacy] Template for constructing input for each participant. Use game_rules instead."
    )
    termination_conditions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Legacy termination conditions. With referee_enabled, the referee determines game over."
    )


class PipelineConfig(BaseModel):
    """Configuration for pipeline mode"""
    step_prompt_template: Optional[str] = Field(
        default=None,
        description="Custom prompt template for each pipeline step. Variables: {input}, {step_description}, {prev_output}"
    )
    pass_context: bool = Field(
        default=True,
        description="Whether to pass all previous outputs (not just the immediate predecessor) to each step"
    )


class VotingConfig(BaseModel):
    """Configuration for voting/ensemble mode"""
    strategy: str = Field(
        default="majority",
        description="Aggregation strategy: 'majority' (most common answer), 'weighted' (weighted by priority), 'best_of' (aggregator picks best)"
    )
    aggregator_prompt: Optional[str] = Field(
        default=None,
        description="Custom prompt for the aggregator (used when strategy='best_of')"
    )


class CollaborationCreate(BaseModel):
    """Request to create a new collaboration"""
    name: str = Field(..., description="Collaboration name")
    description: str = Field(default="", description="Collaboration description")
    mode: CollaborationMode = Field(..., description="Collaboration mode")
    agents: List[CollaborationAgentConfig] = Field(
        default_factory=list,
        description="Agents in this collaboration"
    )
    config_json: Dict[str, Any] = Field(
        default_factory=dict,
        description="Mode-specific configuration"
    )
    enabled: bool = Field(default=True, description="Whether collaboration is enabled")


class CollaborationUpdate(BaseModel):
    """Request to update a collaboration"""
    name: Optional[str] = None
    description: Optional[str] = None
    mode: Optional[CollaborationMode] = None
    agents: Optional[List[CollaborationAgentConfig]] = None
    config_json: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class CollaborationResponse(BaseModel):
    """Collaboration response"""
    id: str = Field(..., description="Collaboration ID")
    name: str
    description: str = ""
    mode: CollaborationMode
    config_json: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    agents: List[CollaborationAgentConfig] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    usage_count: int = 0


class CollaborationTaskResponse(BaseModel):
    """Collaboration task execution response"""
    task_id: str
    collaboration_id: str
    input: str
    output: Optional[str] = None
    status: str
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


# Template definitions for front-end
class CollaborationTemplate(BaseModel):
    """Predefined collaboration template"""
    name: str
    description: str
    mode: CollaborationMode
    default_agents: List[Dict[str, str]]  # List of {role: xxx, description: xxx}
    default_config: Dict[str, Any]


# Built-in templates
TEMPLATES = {
    "supervisor_basic": CollaborationTemplate(
        name="监督者模式",
        description="1个监督者Agent + 多个子Agent，监督者拆分任务后并行执行",
        mode=CollaborationMode.SUPERVISOR,
        default_agents=[
            {"role": "supervisor", "description": "监督者，负责拆分任务和汇总结果"},
            {"role": "child", "description": "子Agent 1，执行子任务"},
            {"role": "child", "description": "子Agent 2，执行子任务"},
        ],
        default_config={
            "split_prompt": None,
            "parallel_execution": True,
            "summary_prompt": None,
        }
    ),
    "adversarial_gen_dis": CollaborationTemplate(
        name="生成-判别对抗模式",
        description="1个生成Agent + 1个判别Agent，生成内容后由判别器校验，循环优化",
        mode=CollaborationMode.ADVERSARIAL_GEN_DIS,
        default_agents=[
            {"role": "generator", "description": "生成Agent，产出内容"},
            {"role": "discriminator", "description": "判别Agent，校验内容质量"},
        ],
        default_config={
            "max_rounds": 3,
            "judge_enabled": False,
            "termination_on_pass": True,
        }
    ),
    "simultaneous_game": CollaborationTemplate(
        name="同时行动博弈（如石头剪刀布）",
        description="所有参与者同时行动，裁判裁决每轮胜负，适用于石头剪刀布、拍卖等场景",
        mode=CollaborationMode.ADVERSARIAL_GAME,
        default_agents=[
            {"role": "participant", "description": "参与者1"},
            {"role": "participant", "description": "参与者2"},
            {"role": "referee", "description": "裁判，裁决每轮胜负和游戏结束"},
        ],
        default_config={
            "turn_strategy": "simultaneous",
            "max_rounds": 10,
            "game_rules": "",
            "referee_enabled": True,
            "referee_prompt": None,
            "shared_state": {},
        }
    ),
    "turn_based_game": CollaborationTemplate(
        name="轮流行动博弈（如下棋）",
        description="参与者按顺序轮流行动，裁判判定胜负，适用于棋类、扑克等场景",
        mode=CollaborationMode.ADVERSARIAL_GAME,
        default_agents=[
            {"role": "participant", "description": "先手玩家"},
            {"role": "participant", "description": "后手玩家"},
            {"role": "referee", "description": "裁判，判定胜负和游戏结束"},
        ],
        default_config={
            "turn_strategy": "turn_based",
            "participant_order": ["participant_0", "participant_1"],
            "max_rounds": 50,
            "game_rules": "",
            "referee_enabled": True,
            "referee_prompt": None,
            "shared_state": {},
        }
    ),
    "pipeline_basic": CollaborationTemplate(
        name="流水线模式",
        description="多个Agent按顺序依次处理，每个Agent的输出作为下一个的输入",
        mode=CollaborationMode.PIPELINE,
        default_agents=[
            {"role": "worker", "description": "步骤1：初步处理"},
            {"role": "worker", "description": "步骤2：深度加工"},
            {"role": "worker", "description": "步骤3：最终输出"},
        ],
        default_config={
            "pass_context": True,
        }
    ),
    "voting_basic": CollaborationTemplate(
        name="投票集成模式",
        description="多个Agent独立回答同一问题，聚合器汇总选出最终答案",
        mode=CollaborationMode.VOTING,
        default_agents=[
            {"role": "voter", "description": "投票者1：独立分析"},
            {"role": "voter", "description": "投票者2：独立分析"},
            {"role": "voter", "description": "投票者3：独立分析"},
            {"role": "aggregator", "description": "聚合器：汇总投票结果"},
        ],
        default_config={
            "strategy": "best_of",
        }
    ),
}
