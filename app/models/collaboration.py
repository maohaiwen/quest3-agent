"""Collaboration models for multi-agent collaboration framework"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from app.utils.timezone import beijing_now
from enum import Enum


class ArtifactType(str, Enum):
    """Collaboration artifact type"""
    TEXT = "text"
    CODE = "code"
    DATA = "data"
    CHART = "chart"
    FILE = "file"


class Artifact(BaseModel):
    """Collaboration artifact - structured output produced by agents"""
    id: str = Field(..., description="Artifact ID")
    collaboration_id: str = Field(..., description="Collaboration ID")
    task_id: str = Field(default="", description="Task ID")
    round: int = Field(default=1, description="Iteration round number")
    producer_agent_id: str = Field(default="", description="Agent that produced this artifact")
    producer_role: str = Field(default="", description="Role of the producing agent")
    name: str = Field(..., description="Artifact name (e.g. '策略思路', '回测代码')")
    artifact_type: ArtifactType = Field(default=ArtifactType.TEXT, description="Artifact type")
    content: str = Field(..., description="Artifact content")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Extra metadata")
    created_at: datetime = Field(default_factory=beijing_now, description="Creation timestamp")


class ArtifactResponse(BaseModel):
    """API response for artifact"""
    id: str
    collaboration_id: str
    task_id: Optional[str] = None
    round: int = 1
    producer_agent_id: str
    producer_role: str
    name: str
    artifact_type: ArtifactType
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class IterationConfig(BaseModel):
    """Iteration capability configuration - can be overlaid on any collaboration mode"""
    enabled: bool = Field(default=False, description="Whether iteration is enabled")
    max_iterations: int = Field(default=3, description="Maximum iteration rounds")
    evaluator: Optional["CollaborationAgentConfig"] = Field(
        default=None, description="Evaluator agent config (uses LLM direct if not provided)"
    )
    evaluator_prompt: Optional[str] = Field(
        default=None, description="Evaluation prompt template (used when no evaluator agent)"
    )
    feedback_strategy: str = Field(
        default="full",
        description="Feedback strategy: 'full' = re-run entire round with feedback"
    )


class CollaborationMode(str, Enum):
    """Collaboration mode"""
    SUPERVISOR = "supervisor"
    PIPELINE = "pipeline"
    VOTING = "voting"
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
    # Game mode
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
    is_human: bool = Field(default=False, description="Whether this is a human node (pause and wait for frontend input instead of calling LLM)")


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


class AdversarialGameConfig(BaseModel):
    """Configuration for adversarial game mode"""
    turn_strategy: str = Field(
        default="simultaneous",
        description="Turn strategy: 'simultaneous' (all act at once) or 'sequential' (act in order, one round = all participants act once)"
    )
    referee_timing: str = Field(
        default="per_round",
        description="When referee judges: 'per_round' (after each round) or 'final' (once after all rounds)"
    )
    max_rounds: int = Field(default=10, description="Maximum game rounds")
    game_rules: str = Field(
        default="",
        description="Game rules description, used to build prompts for participants and referee"
    )
    participant_order: List[str] = Field(
        default_factory=list,
        description="Order of participants for sequential strategy (role identifiers)"
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
        description="Custom prompt for referee (used as prefix, system appends context automatically)"
    )
    round_input_template: Optional[str] = Field(
        default=None,
        description="Custom instruction for each participant (used as prefix, system appends context automatically)"
    )
    sandbox: Optional[str] = Field(
        default=None,
        description="Sandbox type name. When set, provides structured environment with tools"
    )
    sandbox_config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Sandbox initialization parameters"
    )


class PipelineConfig(BaseModel):
    """Configuration for pipeline mode"""
    step_prompt_template: Optional[str] = Field(
        default=None,
        description="Custom instruction for each pipeline step (used as prefix, system appends context automatically)"
    )
    pass_context: bool = Field(
        default=True,
        description="Whether to pass all previous outputs (not just the immediate predecessor) to each step"
    )


class VotingConfig(BaseModel):
    """Configuration for voting/ensemble mode"""
    strategy: str = Field(
        default="majority",
        description="Aggregation strategy: 'majority' (most common answer)"
    )
    aggregator_prompt: Optional[str] = Field(
        default=None,
        description="Custom prompt for the aggregator"
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
    created_at: datetime = Field(default_factory=beijing_now)
    updated_at: datetime = Field(default_factory=beijing_now)
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
    default_agents: List[Dict[str, Any]]  # List of {role: xxx, description: xxx, is_human: bool, ...}
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
    "simultaneous_game": CollaborationTemplate(
        name="同时行动博弈（如石头剪刀布）",
        description="所有参与者同时行动，裁判每轮裁决，适用于石头剪刀布、拍卖等场景",
        mode=CollaborationMode.ADVERSARIAL_GAME,
        default_agents=[
            {"role": "participant", "description": "参与者1"},
            {"role": "participant", "description": "参与者2"},
            {"role": "referee", "description": "裁判，裁决每轮胜负和游戏结束"},
        ],
        default_config={
            "turn_strategy": "simultaneous",
            "referee_timing": "per_round",
            "max_rounds": 10,
            "game_rules": "",
            "referee_enabled": True,
            "referee_prompt": None,
            "shared_state": {},
        }
    ),
    "sequential_game": CollaborationTemplate(
        name="顺序行动博弈",
        description="参与者按顺序行动，裁判每轮裁决，适用于棋类、扑克等场景",
        mode=CollaborationMode.ADVERSARIAL_GAME,
        default_agents=[
            {"role": "participant", "description": "先手玩家"},
            {"role": "participant", "description": "后手玩家"},
            {"role": "referee", "description": "裁判，判定胜负和游戏结束"},
        ],
        default_config={
            "turn_strategy": "sequential",
            "referee_timing": "per_round",
            "participant_order": ["participant_0", "participant_1"],
            "max_rounds": 50,
            "game_rules": "",
            "referee_enabled": True,
            "referee_prompt": None,
            "shared_state": {},
        }
    ),
    "debate": CollaborationTemplate(
        name="辩论模式",
        description="正反双方交替发言辩论，所有轮次结束后裁判终裁胜负",
        mode=CollaborationMode.ADVERSARIAL_GAME,
        default_agents=[
            {"role": "participant", "description": "正方辩手"},
            {"role": "participant", "description": "反方辩手"},
            {"role": "referee", "description": "裁判，辩论结束后评判胜负"},
        ],
        default_config={
            "turn_strategy": "sequential",
            "referee_timing": "final",
            "participant_order": ["participant_0", "participant_1"],
            "max_rounds": 3,
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
            "strategy": "majority",
        }
    ),
    "quant_research_loop": CollaborationTemplate(
        name="量化研究迭代模式",
        description="研究员探索思路→代码专家编码→验证器评估，不通过则整轮迭代优化，支持产物管理",
        mode=CollaborationMode.PIPELINE,
        default_agents=[
            {"role": "worker", "description": "量化研究员：探索策略思路和因子选择"},
            {"role": "worker", "description": "代码专家：将策略思路转化为可执行的Python代码"},
            {"role": "worker", "description": "验证器：运行回测并评估策略绩效指标"},
        ],
        default_config={
            "pass_context": True,
            "iteration": {
                "enabled": True,
                "max_iterations": 3,
                "evaluator_prompt": "你是一个量化策略评估专家。请评估以下策略的回测结果是否达标。\n\n评估标准：\n1. 年化收益率是否为正且合理（>5%）\n2. 最大回撤是否在可接受范围内（<30%）\n3. 夏普比率是否达标（>1.0）\n4. 策略逻辑是否完整，代码是否有明显bug\n\n如果达标，回复：通过\n如果不达标，回复：未通过，并说明具体哪些指标不达标以及改进建议。",
                "feedback_strategy": "full",
            },
        }
    ),
    "chinese_chess": CollaborationTemplate(
        name="中国象棋对弈",
        description="两个智能体在中国象棋沙箱中对弈，沙箱提供棋盘、走棋工具和规则校验",
        mode=CollaborationMode.ADVERSARIAL_GAME,
        default_agents=[
            {"role": "participant", "description": "红方棋手"},
            {"role": "participant", "description": "黑方棋手"},
            {"role": "referee", "description": "裁判，辅助判定和播报"},
        ],
        default_config={
            "turn_strategy": "sequential",
            "referee_timing": "per_round",
            "participant_order": ["participant_0", "participant_1"],
            "max_rounds": 100,
            "game_rules": "中国象棋规则",
            "referee_enabled": True,
            "referee_prompt": None,
            "shared_state": {},
            "sandbox": "chinese_chess",
            "sandbox_config": {},
        }
    ),
    "chinese_chess_human": CollaborationTemplate(
        name="人机象棋对弈",
        description="人与AI在中国象棋沙箱中对弈，人类为红方先手",
        mode=CollaborationMode.ADVERSARIAL_GAME,
        default_agents=[
            {"role": "participant", "description": "红方（人类）", "is_human": True},
            {"role": "participant", "description": "黑方（AI）"},
            {"role": "referee", "description": "裁判"},
        ],
        default_config={
            "turn_strategy": "sequential",
            "referee_timing": "per_round",
            "participant_order": ["participant_0", "participant_1"],
            "max_rounds": 100,
            "game_rules": "中国象棋规则",
            "referee_enabled": True,
            "referee_prompt": None,
            "shared_state": {},
            "sandbox": "chinese_chess",
            "sandbox_config": {},
        }
    ),
}
