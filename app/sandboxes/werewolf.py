"""Werewolf (狼人杀) sandbox for multi-agent collaboration.

Provides a structured game environment where agents play a classic
Werewolf game with role assignment, night/day cycles, and win detection.

Supports 6–12 players (dynamic role distribution).
Multiple participants can share the same agent — the sandbox uses
indexed_role (participant_0, participant_1, …) as the unique key.

Game flow:
    Night → Werewolves choose target → Seer checks → Witch acts → Guard protects
    Day   → Announce deaths → Vote to eliminate
    Win   → All werewolves dead (good wins) or werewolves >= good players (evil wins)
"""
import logging
import random
from collections import Counter
from typing import Dict, List, Any, Optional

from app.core.tool_manager import ToolDefinition
from app.sandboxes.base import BaseSandbox

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Role definitions
# ---------------------------------------------------------------------------

WEREWOLF = "werewolf"
SEER = "seer"
WITCH = "witch"
HUNTER = "hunter"
GUARD = "guard"
VILLAGER = "villager"

ROLE_INFO = {
    WEREWOLF: {"name": "狼人", "icon": "🐺", "team": "evil"},
    SEER:     {"name": "预言家", "icon": "🔮", "team": "good"},
    WITCH:    {"name": "女巫", "icon": "🧙‍♀️", "team": "good"},
    HUNTER:   {"name": "猎人", "icon": "🏹", "team": "good"},
    GUARD:    {"name": "守卫", "icon": "🛡️", "team": "good"},
    VILLAGER: {"name": "平民", "icon": "👤", "team": "good"},
}

# Default 9-player role distribution
DEFAULT_ROLES = [WEREWOLF, WEREWOLF, SEER, WITCH, HUNTER, GUARD,
                 VILLAGER, VILLAGER, VILLAGER]

# Role distribution by player count
ROLE_DISTRIBUTIONS: Dict[int, List[str]] = {
    6:  [WEREWOLF, WEREWOLF, SEER, WITCH, GUARD, VILLAGER],
    7:  [WEREWOLF, WEREWOLF, SEER, WITCH, HUNTER, VILLAGER, VILLAGER],
    8:  [WEREWOLF, WEREWOLF, SEER, WITCH, HUNTER, GUARD, VILLAGER, VILLAGER],
    9:  DEFAULT_ROLES,
    10: [WEREWOLF, WEREWOLF, WEREWOLF, SEER, WITCH, HUNTER, GUARD,
         VILLAGER, VILLAGER, VILLAGER],
    11: [WEREWOLF, WEREWOLF, WEREWOLF, SEER, WITCH, HUNTER, GUARD,
         VILLAGER, VILLAGER, VILLAGER, VILLAGER],
    12: [WEREWOLF, WEREWOLF, WEREWOLF, SEER, WITCH, HUNTER, GUARD,
         VILLAGER, VILLAGER, VILLAGER, VILLAGER, VILLAGER],
}

# Phase constants
NIGHT_WEREWOLF = "night_werewolf"
NIGHT_SEER = "night_seer"
NIGHT_WITCH = "night_witch"
NIGHT_GUARD = "night_guard"
DAY_ANNOUNCE = "day_announce"
DAY_SPEAK = "day_speak"
DAY_VOTE = "day_vote"
GAME_OVER = "game_over"


# ---------------------------------------------------------------------------
# Player state
# ---------------------------------------------------------------------------

class PlayerState:
    """Tracks a single player's state throughout the game."""

    def __init__(self, indexed_role: str, role: str, seat: int):
        self.indexed_role = indexed_role  # unique key: "participant_0", etc.
        self.game_role = role              # werewolf, seer, etc.
        self.seat = seat                   # 1-based seat number
        self.alive: bool = True
        self.death_reason: Optional[str] = None
        # Seer-specific
        self.seer_results: List[Dict[str, Any]] = []
        # Hunter-specific
        self.hunter_can_shoot: bool = True

    @property
    def team(self) -> str:
        return ROLE_INFO[self.game_role]["team"]

    @property
    def is_werewolf(self) -> bool:
        return self.game_role == WEREWOLF


# ---------------------------------------------------------------------------
# WerewolfSandbox
# ---------------------------------------------------------------------------

class WerewolfSandbox(BaseSandbox):
    """Werewolf (狼人杀) sandbox.

    Manages the game state, validates actions, resolves night phases,
    counts votes, and detects win conditions.

    Key design: uses indexed_role (participant_0, participant_1, …) as
    the primary key so that multiple participants can share the same
    underlying agent.
    """

    description = "狼人杀沙箱 — 多名智能体进行经典狼人杀游戏"

    @property
    def supports_sub_phases(self) -> bool:
        return True

    def is_private_phase(self) -> bool:
        """Night phases are private — players should NOT see each other's actions."""
        return self.phase.startswith("night_")

    @property
    def anonymize_identities(self) -> bool:
        """Werewolf hides agent identities — show seat numbers, not agent names."""
        return True

    def get_anonymous_identity(self, indexed_role: str) -> Dict[str, str]:
        """Return anonymized identity for display: seat-based name, not real agent id.

        Returns dict with:
            agent_id: "seat_N"  — anonymized ID for frontend keying
            display_name: "N号玩家" — human-readable display name
            role: "seat_N" — anonymized role badge
        """
        player = self.players.get(indexed_role)
        seat = player.seat if player else 1
        return {
            "agent_id": f"seat_{seat}",
            "display_name": f"{seat}号玩家",
            "role": f"seat_{seat}",
        }

    def __init__(self):
        # Game state — keyed by indexed_role (unique per participant)
        self.phase: str = NIGHT_WEREWOLF
        self.players: Dict[str, PlayerState] = {}  # indexed_role → PlayerState
        self.seat_map: Dict[int, str] = {}          # seat → indexed_role
        self.human_roles: set = set()                # indexed_roles that are human players
        self.round_num: int = 0

        # Night state — values are indexed_role
        self._night_target: Optional[str] = None
        self._night_werewolf_votes: Dict[str, str] = {}  # indexed_role → target indexed_role
        self._night_seer_result: Optional[Dict] = None
        self._night_guard_target: Optional[str] = None
        self._night_deaths: List[str] = []
        self._last_night_msg: str = ""  # Public announcement from last night

        # Witch state
        self._witch_antidote_used: bool = False
        self._witch_poison_used: bool = False
        self._witch_poison_target: Optional[str] = None

        # Guard state
        self._guard_last_protected: Optional[str] = None

        # Day state
        self._votes: Dict[str, str] = {}  # voter indexed_role → target indexed_role
        self._day_eliminated: Optional[str] = None
        self._day_speakers: List[str] = []  # indexed_roles who have spoken this day
        self._day_speeches: List[Dict[str, str]] = []  # {seat, content} per speech
        self._all_speeches_by_round: Dict[int, List[Dict[str, str]]] = {}  # round → [{seat, content}]

        # Game log
        self._log: List[Dict[str, Any]] = []

        # Win state
        self._game_over: bool = False
        self._winner: Optional[str] = None  # "good" or "evil"
        self._game_over_reason: str = ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_task_start(self, agents: List[Dict[str, Any]]) -> None:
        """Map agents to roles and seats using indexed_role as key."""
        participants = [a for a in agents if a.get("role") != "referee"]
        n = len(participants)

        roles = list(ROLE_DISTRIBUTIONS.get(n, self._auto_distribute(n)))
        random.shuffle(roles)

        for i, agent in enumerate(participants):
            indexed_role = agent.get("role", f"participant_{i}")
            game_role = roles[i] if i < len(roles) else VILLAGER
            seat = i + 1
            player = PlayerState(indexed_role, game_role, seat)
            self.players[indexed_role] = player
            self.seat_map[seat] = indexed_role
            if agent.get("is_human"):
                self.human_roles.add(indexed_role)

        self.round_num = 1
        self.phase = NIGHT_WEREWOLF
        self._log.append({"round": 0, "phase": "setup", "msg": "游戏开始，角色已分配"})

    def on_task_end(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Sub-phase support (for GameCollaboration engine)
    # ------------------------------------------------------------------

    def get_active_participants(self) -> List[tuple]:
        """Return which participants should act in the current phase.

        Auto-advances through phases whose role is dead (e.g. dead witch
        means NIGHT_WITCH is skipped).  Without this, the sub-phase loop
        in the game engine would break on an empty list and the game would
        stall forever.

        Returns list of (indexed_role,) tuples.  The engine looks up the
        corresponding agent from its participants list.
        """
        if self._game_over:
            return []

        # Try current phase; if no active participants, auto-advance.
        # Safety limit prevents infinite loop on unexpected state.
        for _ in range(5):
            active = self._get_active_for_phase(self.phase)
            if active:
                return active

            # No one can act in this phase — skip it
            if not self._auto_advance_phase():
                return []  # game over or stuck

        return []

    def _get_active_for_phase(self, phase: str) -> List[tuple]:
        """Return active participants for a specific phase (no side effects)."""
        active = []
        if phase == NIGHT_WEREWOLF:
            for p in self.players.values():
                if p.alive and p.is_werewolf:
                    active.append((p.indexed_role,))
        elif phase == NIGHT_SEER:
            for p in self.players.values():
                if p.alive and p.game_role == SEER:
                    active.append((p.indexed_role,))
        elif phase == NIGHT_WITCH:
            for p in self.players.values():
                if p.alive and p.game_role == WITCH:
                    active.append((p.indexed_role,))
        elif phase == NIGHT_GUARD:
            for p in self.players.values():
                if p.alive and p.game_role == GUARD:
                    active.append((p.indexed_role,))
        elif phase == DAY_SPEAK:
            for p in sorted(self.players.values(), key=lambda x: x.seat):
                if p.alive and p.indexed_role not in self._day_speakers:
                    active.append((p.indexed_role,))
        elif phase == DAY_VOTE:
            for p in sorted(self.players.values(), key=lambda x: x.seat):
                if p.alive:
                    active.append((p.indexed_role,))
        return active

    def _auto_advance_phase(self) -> bool:
        """Skip a phase whose role is dead and advance to the next one.

        Returns True if we advanced to another phase (caller should retry
        get_active_participants), False if the game is over or we cannot
        advance.
        """
        if self.phase == NIGHT_WEREWOLF:
            # No werewolves alive → good team should have already won.
            # Check just in case.
            result = self._check_win()
            if result:
                self.phase = GAME_OVER
                self._game_over = True
                self._winner = result["winner"]
                self._game_over_reason = result["reason"]
            return False

        elif self.phase == NIGHT_SEER:
            self.phase = NIGHT_WITCH
            self._log.append({
                "round": self.round_num, "phase": "night_seer",
                "msg": "预言家已出局，跳过查验阶段"
            })
            return True

        elif self.phase == NIGHT_WITCH:
            self.phase = NIGHT_GUARD
            self._log.append({
                "round": self.round_num, "phase": "night_witch",
                "msg": "女巫已出局，跳过女巫行动阶段"
            })
            return True

        elif self.phase == NIGHT_GUARD:
            # Guard is dead — resolve night directly (no protection)
            self._log.append({
                "round": self.round_num, "phase": "night_guard",
                "msg": "守卫已出局，跳过守护阶段"
            })
            self._resolve_night()
            return not self._game_over

        elif self.phase == DAY_ANNOUNCE:
            # Day announcement has no active participants — advance to speak
            self.phase = DAY_SPEAK
            self._day_speakers.clear()
            self._day_speeches.clear()
            self._votes.clear()
            return True

        elif self.phase == DAY_SPEAK:
            # All players have spoken — move to voting
            self.phase = DAY_VOTE
            self._votes.clear()
            self._log.append({
                "round": self.round_num, "phase": "day_speak",
                "msg": "发言阶段结束，进入投票"
            })
            return True

        # DAY_VOTE or other phases — cannot auto-advance
        return False

    def get_phase_description(self) -> str:
        """Return a short description of the current phase for the frontend.

        Night phases use immersive narrator-style descriptions (like a
        real moderator), showing role names but NOT player identities.
        """
        night_map = {
            NIGHT_WEREWOLF: "🌙 天黑请闭眼…狼人请睁眼，选择击杀目标",
            NIGHT_SEER:     "🔮 预言家请睁眼，选择查验目标",
            NIGHT_WITCH:    "🧙‍♀️ 女巫请睁眼，选择是否使用药剂",
            NIGHT_GUARD:    "🛡️ 守卫请睁眼，选择守护目标",
        }
        if self.phase in night_map:
            return night_map[self.phase]
        return self._phase_cn()

    # ------------------------------------------------------------------
    # Tool definitions
    # ------------------------------------------------------------------

    def get_tools_for_agent(self, agent_id: str, role: str) -> List[ToolDefinition]:
        """Return tools based on current phase and agent's role."""
        if role == "referee":
            return []

        player = self.players.get(role)
        if not player or not player.alive:
            # Dead hunter can still shoot
            if player and player.game_role == HUNTER and player.hunter_can_shoot and not player.alive:
                return [ToolDefinition(
                    name="hunter_shoot",
                    description="猎人开枪！选择一名玩家将其带走。",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "target": {
                                "type": "string",
                                "description": "要开枪射杀的玩家座位号"
                            }
                        },
                        "required": ["target"]
                    },
                    handler=None,
                    source="sandbox",
                )]
            return []

        tools = []

        if self.phase == NIGHT_WEREWOLF and player.is_werewolf:
            tools.append(self._night_action_tool("选择今晚要击杀的玩家"))
        elif self.phase == NIGHT_SEER and player.game_role == SEER:
            tools.append(self._night_action_tool("选择今晚要查验的玩家"))
        elif self.phase == NIGHT_WITCH and player.game_role == WITCH:
            tools.append(self._witch_action_tool())
        elif self.phase == NIGHT_GUARD and player.game_role == GUARD:
            tools.append(self._night_action_tool("选择今晚要守护的玩家"))

        if self.phase == DAY_VOTE:
            tools.append(ToolDefinition(
                name="vote",
                description="投票放逐一名玩家，或弃票。投票获得多数的玩家将被淘汰。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                            "description": "要投票放逐的玩家座位号，弃票填0"
                        }
                    },
                    "required": ["target"]
                },
                handler=None,
                source="sandbox",
            ))

        return tools

    def _night_action_tool(self, description: str) -> ToolDefinition:
        return ToolDefinition(
            name="night_action",
            description=description,
            input_schema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "目标玩家的座位号"
                    }
                },
                "required": ["target"]
            },
            handler=None,
            source="sandbox",
        )

    def _witch_action_tool(self) -> ToolDefinition:
        desc_parts = []
        if not self._witch_antidote_used:
            desc_parts.append("可使用 witch_action='heal' 救活今晚被杀的玩家")
        if not self._witch_poison_used:
            desc_parts.append("可使用 witch_action='poison' 毒杀一名玩家（需提供 target）")
        if not desc_parts:
            desc_parts.append("你的技能已全部使用完毕，可使用 witch_action='skip' 跳过")

        return ToolDefinition(
            name="night_action",
            description="女巫夜间行动。" + "；".join(desc_parts),
            input_schema={
                "type": "object",
                "properties": {
                    "witch_action": {
                        "type": "string",
                        "enum": ["heal", "poison", "skip"],
                        "description": "heal=救人, poison=毒人, skip=跳过"
                    },
                    "target": {
                        "type": "string",
                        "description": "毒杀目标的座位号（仅 poison 时需要）"
                    }
                },
                "required": ["witch_action"]
            },
            handler=None,
            source="sandbox",
        )

    # ------------------------------------------------------------------
    # State views (information hiding)
    # ------------------------------------------------------------------

    def get_state_view(self, agent_id: str, role: str) -> str:
        """Return game state visible to this agent."""
        if role == "referee":
            return self._referee_view()

        player = self.players.get(role)
        if not player:
            return "你不在游戏中。"

        parts = []

        role_info = ROLE_INFO[player.game_role]
        phase_cn = self._phase_cn()

        # During day phases (DAY_SPEAK / DAY_VOTE), show public info
        # plus the player's OWN private info (seer results, potion status,
        # werewolf teammates) — they should remember what they know.
        is_day = self.phase in (DAY_SPEAK, DAY_VOTE)

        parts.append(f"你是{role_info['name']}（{role_info['icon']}），座位号{player.seat}。")
        parts.append(f"当前：第{self.round_num}轮 · {phase_cn}")

        # Public game rules — shown to all players in all phases
        parts.append(self._public_rules_hint(player))

        # --- Own private info (visible in ALL phases) ---
        # Werewolf teammates (including dead)
        if player.is_werewolf:
            teammates = [p for p in self.players.values()
                         if p.is_werewolf and p.indexed_role != role]
            if teammates:
                names = []
                for t in teammates:
                    name = f"{t.seat}号"
                    if not t.alive:
                        name += "(已出局)"
                    names.append(name)
                parts.append(f"你的狼队友：{', '.join(names)}")

        # Seer check results (persist across rounds)
        if player.game_role == SEER and player.seer_results:
            results_str = []
            for r in player.seer_results:
                target_p = self.players.get(r["target_role"])
                seat = target_p.seat if target_p else "?"
                result_cn = "狼人" if r["is_werewolf"] else "好人"
                results_str.append(f"第{r['round']}轮查验{seat}号→{result_cn}")
            parts.append(f"你的查验记录：{'；'.join(results_str)}")

        # Witch potion status
        if player.game_role == WITCH:
            heal_status = "已用" if self._witch_antidote_used else "可用"
            poison_status = "已用" if self._witch_poison_used else "可用"
            parts.append(f"解药：{heal_status}，毒药：{poison_status}")

        # --- Public info ---
        # Alive players
        alive_list = [f"{p.seat}号" for p in sorted(self.players.values(), key=lambda p: p.seat) if p.alive]
        parts.append(f"存活玩家：{', '.join(alive_list)}（共{len(alive_list)}人）")

        # Dead players (with roles revealed — public knowledge)
        dead_list = []
        for p in sorted(self.players.values(), key=lambda p: p.seat):
            if not p.alive:
                role_name = ROLE_INFO[p.game_role]["name"]
                dead_list.append(f"{p.seat}号({role_name})")
        if dead_list:
            parts.append(f"已出局：{', '.join(dead_list)}")

        if is_day:
            # Night result announcement (always show — even for safe nights)
            if self._last_night_msg:
                parts.append(self._last_night_msg)

            # Speech history (current round + all previous rounds)
            all_speech_text = self._build_all_speech_history()
            if all_speech_text:
                parts.append("--- 发言记录 ---")
                parts.append(all_speech_text)

            # Phase-specific hints
            if self.phase == DAY_VOTE:
                votable = [f"{p.seat}号" for p in sorted(self.players.values(), key=lambda p: p.seat)
                           if p.alive and p.indexed_role != role]
                parts.append(f"可投票：{', '.join(votable)}（弃票填0）")

        else:
            # --- Night phase: additional phase-specific hints ---
            if self.phase == NIGHT_WEREWOLF and player.is_werewolf:
                killable = [f"{p.seat}号" for p in sorted(self.players.values(), key=lambda p: p.seat)
                            if p.alive and not p.is_werewolf]
                parts.append(f"可击杀：{', '.join(killable)}")
            elif self.phase == NIGHT_SEER and player.game_role == SEER:
                checkable = [f"{p.seat}号" for p in sorted(self.players.values(), key=lambda p: p.seat)
                             if p.alive and p.indexed_role != role]
                parts.append(f"可查验：{', '.join(checkable)}")
            elif self.phase == NIGHT_WITCH and player.game_role == WITCH:
                if self._night_target and not self._witch_antidote_used:
                    target_p = self.players.get(self._night_target)
                    if target_p:
                        parts.append(f"今晚被杀的是{target_p.seat}号，你可以使用解药救人")
            elif self.phase == NIGHT_GUARD and player.game_role == GUARD:
                guardable = [f"{p.seat}号" for p in sorted(self.players.values(), key=lambda p: p.seat)
                             if p.alive and p.indexed_role != self._guard_last_protected]
                parts.append(f"可守护：{', '.join(guardable)}")
                if self._guard_last_protected:
                    last_p = self.players.get(self._guard_last_protected)
                    if last_p:
                        parts.append(f"（上轮守护了{last_p.seat}号，本轮不可重复）")

        return "\n".join(parts)

    def get_speech_history(self) -> str:
        """Return speech records for the current day phase (seat numbers only)."""
        if not self._day_speeches:
            return ""
        lines = []
        for entry in self._day_speeches:
            lines.append(f"{entry['seat']}号玩家：{entry['content']}")
        return "\n".join(lines)

    def _build_all_speech_history(self) -> str:
        """Return speech history from ALL rounds (previous + current).

        Shows previous rounds' speeches grouped by round, then the
        current round's speeches.  This gives players full context of
        what was said on earlier days.
        """
        sections = []
        # Previous rounds
        for r in sorted(self._all_speeches_by_round.keys()):
            speeches = self._all_speeches_by_round[r]
            if not speeches:
                continue
            lines = [f"{e['seat']}号玩家：{e['content']}" for e in speeches]
            sections.append(f"【第{r}轮】\n" + "\n".join(lines))
        # Current round
        if self._day_speeches:
            lines = [f"{e['seat']}号玩家：{e['content']}" for e in self._day_speeches]
            sections.append(f"【第{self.round_num}轮（当前）】\n" + "\n".join(lines))
        return "\n\n".join(sections)

    def record_speech(self, indexed_role: str, content: str) -> None:
        """Record a player's speech during DAY_SPEAK phase."""
        player = self.players.get(indexed_role)
        if not player:
            return
        self._day_speakers.append(indexed_role)
        self._day_speeches.append({
            "seat": str(player.seat),
            "content": content,
        })

    def _public_rules_hint(self, player: PlayerState) -> str:
        """Return public game rules visible to this player.

        Only includes rules that the player's role would legitimately know.
        Does NOT reveal other players' roles or any private information.
        """
        hints = ["游戏规则：狼人每晚选择击杀一名玩家；白天所有存活玩家依次发言讨论后投票放逐一人。好人阵营（预言家/女巫/守卫/猎人/平民）需找出并放逐所有狼人；狼人阵营需让狼人数量≥好人数量。"]

        if player.game_role == WEREWOLF:
            hints.append("你是狼人，每晚与队友共同选择击杀目标，白天需伪装身份。")
        elif player.game_role == SEER:
            hints.append("你是预言家，每晚可查验一名玩家是好人还是狼人。")
        elif player.game_role == WITCH:
            hints.append("你是女巫，有一瓶解药（救人）和一瓶毒药（毒人），各只能使用一次。")
        elif player.game_role == GUARD:
            hints.append("你是守卫，每晚可守护一名玩家使其免受狼人袭击，不能连续两晚守护同一人。")
        elif player.game_role == HUNTER:
            hints.append("你是猎人，被淘汰时可开枪带走一名玩家。")
        else:
            hints.append("你是平民，没有特殊技能，通过发言和投票帮助好人阵营。")

        return " ".join(hints)

    def _referee_view(self) -> str:
        """Full game state for referee."""
        parts = [f"=== 第{self.round_num}轮 · {self._phase_cn()} ==="]
        for p in sorted(self.players.values(), key=lambda p: p.seat):
            role_name = ROLE_INFO[p.game_role]["name"]
            status = "存活" if p.alive else f"已死({p.death_reason or '未知'})"
            parts.append(f"  {p.seat}号 {role_name} — {status}")

        if self._log:
            parts.append("--- 游戏日志 ---")
            for entry in self._log[-20:]:
                parts.append(f"  R{entry['round']} {entry['phase']}: {entry['msg']}")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Action handling
    # ------------------------------------------------------------------

    async def handle_action(self, agent_id: str, role: str,
                            action: str, **kwargs) -> Dict[str, Any]:
        """Handle a tool call from an agent."""
        if self._game_over:
            return {"success": False, "error": "游戏已结束"}

        # Use role (indexed_role) as the primary key for player lookup
        player = self.players.get(role)
        if not player:
            return {"success": False, "error": "你不在游戏中"}
        if not player.alive and action != "hunter_shoot":
            return {"success": False, "error": "你已出局，无法行动"}

        if action == "night_action":
            return await self._handle_night_action(role, player, **kwargs)
        elif action == "vote":
            return await self._handle_vote(role, player, **kwargs)
        elif action == "hunter_shoot":
            return await self._handle_hunter_shoot(role, player, **kwargs)
        else:
            return {"success": False, "error": f"未知操作: {action}"}

    async def _handle_night_action(self, indexed_role: str, player: PlayerState,
                                    **kwargs) -> Dict[str, Any]:
        """Process a night_action tool call."""
        if self.phase == NIGHT_WEREWOLF:
            return self._werewolf_action(indexed_role, player, **kwargs)
        elif self.phase == NIGHT_SEER:
            return self._seer_action(indexed_role, player, **kwargs)
        elif self.phase == NIGHT_WITCH:
            return self._witch_action(indexed_role, player, **kwargs)
        elif self.phase == NIGHT_GUARD:
            return self._guard_action(indexed_role, player, **kwargs)
        else:
            return {"success": False, "error": "当前不是夜间行动阶段"}

    def _resolve_seat(self, target_str: str) -> Optional[str]:
        """Resolve a seat number string to an indexed_role."""
        try:
            seat = int(target_str)
            return self.seat_map.get(seat)
        except (ValueError, TypeError):
            return None

    def _werewolf_action(self, indexed_role: str, player: PlayerState,
                         **kwargs) -> Dict[str, Any]:
        """Handle werewolf kill target selection."""
        if not player.is_werewolf:
            return {"success": False, "error": "你不是狼人"}
        if self.phase != NIGHT_WEREWOLF:
            return {"success": False, "error": "当前不是狼人行动阶段"}

        target_str = kwargs.get("target", "")
        target_role = self._resolve_seat(target_str)
        if not target_role:
            return {"success": False, "error": f"无效的目标座位号: {target_str}"}

        target = self.players.get(target_role)
        if not target or not target.alive:
            return {"success": False, "error": "目标玩家已出局"}
        if target.is_werewolf:
            return {"success": False, "error": "不能击杀狼队友"}

        self._night_werewolf_votes[indexed_role] = target_role
        seat = target.seat

        # Check if all werewolves have voted
        alive_wolves = [p for p in self.players.values() if p.is_werewolf and p.alive]
        if len(self._night_werewolf_votes) >= len(alive_wolves):
            vote_counts = Counter(self._night_werewolf_votes.values())
            self._night_target = vote_counts.most_common(1)[0][0]
            self._night_werewolf_votes.clear()

            self.phase = NIGHT_SEER
            self._log.append({
                "round": self.round_num, "phase": "night_werewolf",
                "msg": "狼人选择了击杀目标"
            })

        return {"success": True, "message": f"你选择了击杀{seat}号玩家"}

    def _seer_action(self, indexed_role: str, player: PlayerState,
                     **kwargs) -> Dict[str, Any]:
        """Handle seer check action."""
        if player.game_role != SEER:
            return {"success": False, "error": "你不是预言家"}
        if self.phase != NIGHT_SEER:
            return {"success": False, "error": "当前不是预言家行动阶段"}

        target_str = kwargs.get("target", "")
        target_role = self._resolve_seat(target_str)
        if not target_role:
            return {"success": False, "error": f"无效的目标座位号: {target_str}"}

        target = self.players.get(target_role)
        if not target or not target.alive:
            return {"success": False, "error": "目标玩家已出局"}
        if target_role == indexed_role:
            return {"success": False, "error": "不能查验自己"}

        is_wolf = target.is_werewolf
        result_cn = "狼人" if is_wolf else "好人"
        player.seer_results.append({
            "round": self.round_num,
            "target_role": target_role,
            "is_werewolf": is_wolf,
        })

        self.phase = NIGHT_WITCH
        self._log.append({
            "round": self.round_num, "phase": "night_seer",
            "msg": "预言家完成了查验"
        })

        return {"success": True, "message": f"查验结果：{target.seat}号是{result_cn}"}

    def _witch_action(self, indexed_role: str, player: PlayerState,
                      **kwargs) -> Dict[str, Any]:
        """Handle witch action (heal/poison/skip)."""
        if player.game_role != WITCH:
            return {"success": False, "error": "你不是女巫"}
        if self.phase != NIGHT_WITCH:
            return {"success": False, "error": "当前不是女巫行动阶段"}

        action_type = kwargs.get("witch_action", "skip")

        if action_type == "heal":
            if self._witch_antidote_used:
                return {"success": False, "error": "解药已使用"}
            if not self._night_target:
                return {"success": False, "error": "今晚没有人被杀"}
            self._witch_antidote_used = True
            self._night_target = None  # Saved!
            self.phase = NIGHT_GUARD
            self._log.append({
                "round": self.round_num, "phase": "night_witch",
                "msg": "女巫使用了解药"
            })
            return {"success": True, "message": "你使用解药救活了今晚被杀的玩家"}

        elif action_type == "poison":
            if self._witch_poison_used:
                return {"success": False, "error": "毒药已使用"}
            target_str = kwargs.get("target", "")
            target_role = self._resolve_seat(target_str)
            if not target_role:
                return {"success": False, "error": f"无效的目标座位号: {target_str}"}
            target = self.players.get(target_role)
            if not target or not target.alive:
                return {"success": False, "error": "目标玩家已出局"}
            self._witch_poison_used = True
            self._witch_poison_target = target_role
            self.phase = NIGHT_GUARD
            self._log.append({
                "round": self.round_num, "phase": "night_witch",
                "msg": "女巫使用了毒药"
            })
            return {"success": True, "message": f"你对{target.seat}号玩家使用了毒药"}

        else:  # skip
            self.phase = NIGHT_GUARD
            return {"success": True, "message": "你选择跳过本回合"}

    def _guard_action(self, indexed_role: str, player: PlayerState,
                      **kwargs) -> Dict[str, Any]:
        """Handle guard protection action."""
        if player.game_role != GUARD:
            return {"success": False, "error": "你不是守卫"}
        if self.phase != NIGHT_GUARD:
            return {"success": False, "error": "当前不是守卫行动阶段"}

        target_str = kwargs.get("target", "")
        target_role = self._resolve_seat(target_str)
        if not target_role:
            return {"success": False, "error": f"无效的目标座位号: {target_str}"}

        target = self.players.get(target_role)
        if not target or not target.alive:
            return {"success": False, "error": "目标玩家已出局"}
        if target_role == self._guard_last_protected:
            return {"success": False, "error": "不能连续两晚守护同一个人"}

        self._night_guard_target = target_role
        self._guard_last_protected = target_role
        self._log.append({
            "round": self.round_num, "phase": "night_guard",
            "msg": f"守卫守护了{target.seat}号玩家"
        })

        # Resolve night and transition to day
        self._resolve_night()
        return {"success": True, "message": f"你守护了{target.seat}号玩家"}

    def _resolve_night(self) -> None:
        """Resolve all night actions and transition to day."""
        deaths = []

        # Werewolf kill (if not saved by witch or guard)
        if self._night_target:
            target_role = self._night_target
            if target_role != self._night_guard_target:
                self._kill_player(target_role, "被狼人杀害")
                deaths.append(target_role)

        # Witch poison
        if self._witch_poison_target:
            poison_role = self._witch_poison_target
            if poison_role != self._night_guard_target:
                self._kill_player(poison_role, "被女巫毒杀")
                if poison_role not in deaths:
                    deaths.append(poison_role)

        self._night_deaths = deaths

        # Build announcement
        if deaths:
            seats = [str(self.players[d].seat) for d in deaths]
            death_msg = f"昨晚{', '.join(seats)}号玩家出局了"
        else:
            death_msg = "昨晚是平安夜，没有人出局"

        self._last_night_msg = death_msg

        self._log.append({
            "round": self.round_num, "phase": "day_announce",
            "msg": death_msg
        })

        # Reset night state
        self._night_target = None
        self._night_werewolf_votes.clear()
        self._night_seer_result = None
        self._night_guard_target = None
        self._witch_poison_target = None

        # Check win after night
        result = self._check_win()
        if result:
            self.phase = GAME_OVER
            self._game_over = True
            self._winner = result["winner"]
            self._game_over_reason = result["reason"]
            return

        # Transition to day: speak first, then vote
        self.phase = DAY_SPEAK
        # Archive any previous speeches before clearing (safety for first round)
        if self._day_speeches:
            self._all_speeches_by_round[self.round_num] = list(self._day_speeches)
        self._day_speakers.clear()
        self._day_speeches.clear()
        self._votes.clear()

    async def _handle_vote(self, indexed_role: str, player: PlayerState,
                           **kwargs) -> Dict[str, Any]:
        """Handle a vote during day phase. target=0 or empty means abstain."""
        if self.phase != DAY_VOTE:
            return {"success": False, "error": "当前不是投票阶段"}

        target_str = kwargs.get("target", "")

        # Abstain: target is "0" or empty
        is_abstain = not target_str.strip() or target_str.strip() == "0"

        if is_abstain:
            # Record abstention — value None means abstained
            self._votes[indexed_role] = None
            # Check if all alive players have voted
            alive_count = sum(1 for p in self.players.values() if p.alive)
            if len(self._votes) >= alive_count:
                self._resolve_votes()
            return {"success": True, "message": "你选择了弃票"}

        target_role = self._resolve_seat(target_str)
        if not target_role:
            return {"success": False, "error": f"无效的目标座位号: {target_str}"}

        target = self.players.get(target_role)
        if not target or not target.alive:
            return {"success": False, "error": "目标玩家已出局"}

        self._votes[indexed_role] = target_role
        seat = target.seat

        # Check if all alive players have voted
        alive_count = sum(1 for p in self.players.values() if p.alive)
        if len(self._votes) >= alive_count:
            self._resolve_votes()
        return {"success": True, "message": f"你投票放逐{seat}号玩家"}

    def _resolve_votes(self) -> None:
        """Tally votes and resolve the day vote outcome."""
        # Filter out abstentions (None values)
        valid_votes = {voter: target for voter, target in self._votes.items() if target is not None}

        if not valid_votes:
            self._log.append({
                "round": self.round_num, "phase": "day_vote",
                "msg": "全员弃票，无人被放逐"
            })
            self._day_eliminated = None
        else:
            vote_counts = Counter(valid_votes.values())
            most_common = vote_counts.most_common()

            if len(most_common) > 1 and most_common[0][1] == most_common[1][1]:
                self._log.append({
                    "round": self.round_num, "phase": "day_vote",
                    "msg": "投票平局，无人被放逐"
                })
                self._day_eliminated = None
            else:
                eliminated_role = most_common[0][0]
                eliminated = self.players[eliminated_role]
                self._kill_player(eliminated_role, "被投票放逐")
                self._day_eliminated = eliminated_role
                role_name = ROLE_INFO[eliminated.game_role]["name"]
                self._log.append({
                    "round": self.round_num, "phase": "day_vote",
                    "msg": f"{eliminated.seat}号({role_name})被投票放逐"
                })

        self._votes.clear()

        # Check win after vote
        result = self._check_win()
        if result:
            self.phase = GAME_OVER
            self._game_over = True
            self._winner = result["winner"]
            self._game_over_reason = result["reason"]
        else:
            # Start new night
            # Archive this round's speeches before clearing
            if self._day_speeches:
                self._all_speeches_by_round[self.round_num] = list(self._day_speeches)
            self.round_num += 1
            self.phase = NIGHT_WEREWOLF
            self._night_deaths.clear()
            self._day_speakers.clear()
            self._day_speeches.clear()

    async def _handle_hunter_shoot(self, indexed_role: str, player: PlayerState,
                                   **kwargs) -> Dict[str, Any]:
        """Handle hunter shooting when eliminated."""
        if player.game_role != HUNTER:
            return {"success": False, "error": "你不是猎人"}
        if player.alive:
            return {"success": False, "error": "你还没有出局"}
        if not player.hunter_can_shoot:
            return {"success": False, "error": "你已经开过枪了"}

        target_str = kwargs.get("target", "")
        target_role = self._resolve_seat(target_str)
        if not target_role:
            return {"success": False, "error": f"无效的目标座位号: {target_str}"}

        target = self.players.get(target_role)
        if not target or not target.alive:
            return {"success": False, "error": "目标玩家已出局"}

        player.hunter_can_shoot = False
        self._kill_player(target_role, "被猎人射杀")
        role_name = ROLE_INFO[target.game_role]["name"]
        self._log.append({
            "round": self.round_num, "phase": "hunter",
            "msg": f"猎人射杀了{target.seat}号({role_name})"
        })

        # Check win after hunter shoot
        result = self._check_win()
        if result:
            self.phase = GAME_OVER
            self._game_over = True
            self._winner = result["winner"]
            self._game_over_reason = result["reason"]

        return {"success": True, "message": f"你射杀了{target.seat}号玩家({role_name})"}

    # ------------------------------------------------------------------
    # Game logic helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _auto_distribute(n: int) -> List[str]:
        """Auto-generate a role distribution for non-standard player counts."""
        n_wolves = max(1, n // 3)
        roles = [WEREWOLF] * n_wolves
        roles.append(SEER)
        if n >= 7:
            roles.append(WITCH)
        if n >= 6:
            roles.append(GUARD)
        if n >= 8:
            roles.append(HUNTER)
        while len(roles) < n:
            roles.append(VILLAGER)
        return roles

    def _kill_player(self, indexed_role: str, reason: str) -> None:
        """Mark a player as dead."""
        player = self.players.get(indexed_role)
        if player and player.alive:
            player.alive = False
            player.death_reason = reason

    def _check_win(self) -> Optional[Dict[str, Any]]:
        """Check if the game has ended."""
        alive_wolves = sum(1 for p in self.players.values() if p.alive and p.is_werewolf)
        alive_good = sum(1 for p in self.players.values() if p.alive and not p.is_werewolf)

        if alive_wolves == 0:
            return {"game_over": True, "winner": "good", "reason": "所有狼人已被淘汰，好人阵营获胜！"}
        if alive_wolves >= alive_good:
            return {"game_over": True, "winner": "evil", "reason": "狼人数量≥好人，狼人阵营获胜！"}
        return None

    def check_termination(self) -> Optional[Dict[str, Any]]:
        """Check if the game has ended."""
        if not self._game_over:
            return None
        return {
            "game_over": True,
            "winner": self._winner,
            "reason": self._game_over_reason,
        }

    def get_action_hint(self, agent_id: str, role: str) -> Optional[str]:
        """Return a hint about how to act."""
        if role == "referee":
            return None
        player = self.players.get(role)
        if not player:
            return None

        if self.phase == NIGHT_WEREWOLF and player.is_werewolf:
            return "请使用 night_action 工具选择今晚要击杀的玩家座位号。"
        elif self.phase == NIGHT_SEER and player.game_role == SEER:
            return "请使用 night_action 工具选择今晚要查验的玩家座位号。"
        elif self.phase == NIGHT_WITCH and player.game_role == WITCH:
            return "请使用 night_action 工具（witch_action='heal'救人/witch_action='poison'毒人/witch_action='skip'跳过）。"
        elif self.phase == NIGHT_GUARD and player.game_role == GUARD:
            return "请使用 night_action 工具选择今晚要守护的玩家座位号。"
        elif self.phase == DAY_SPEAK and player.alive:
            return "请发表你的看法，分析场上局势，注意不要暴露你的身份信息。直接输出文字即可，无需使用工具。"
        elif self.phase == DAY_VOTE and player.alive:
            return "请使用 vote 工具投票放逐一名玩家（弃票填0）。"
        elif not player.alive and player.game_role == HUNTER and player.hunter_can_shoot:
            return "你已出局！请使用 hunter_shoot 工具选择一名玩家带走。"
        return None

    async def parse_action_output(self, agent_id: str, role: str,
                                  text: str) -> Optional[Dict[str, Any]]:
        """Try to extract actions from free-text output."""
        if self._game_over:
            return None

        player = self.players.get(role)
        if not player:
            return None

        import re

        # Check for abstention keywords in vote phase
        if self.phase == DAY_VOTE and player.alive:
            if re.search(r'弃票|弃权|放弃|跳过|abstain', text, re.IGNORECASE):
                return await self.handle_action(agent_id, role, "vote", target="0")

        seat_match = re.search(r'(\d+)\s*号', text)
        if not seat_match:
            seat_match = re.search(r'目标[是为：]\s*(\d+)', text)

        if seat_match:
            target = seat_match.group(1)

            if self.phase in (NIGHT_WEREWOLF, NIGHT_SEER, NIGHT_GUARD) and player.alive:
                return await self.handle_action(agent_id, role, "night_action", target=target)
            elif self.phase == DAY_VOTE and player.alive:
                return await self.handle_action(agent_id, role, "vote", target=target)
            elif not player.alive and player.game_role == HUNTER and player.hunter_can_shoot:
                return await self.handle_action(agent_id, role, "hunter_shoot", target=target)

        if self.phase == NIGHT_WITCH and player.game_role == WITCH and player.alive:
            if "救人" in text or "解药" in text or "heal" in text.lower():
                return await self.handle_action(agent_id, role, "night_action", witch_action="heal")
            elif "毒" in text or "poison" in text.lower():
                if seat_match:
                    return await self.handle_action(agent_id, role, "night_action",
                                                   witch_action="poison", target=seat_match.group(1))

        return None

    # ------------------------------------------------------------------
    # Phase display helpers
    # ------------------------------------------------------------------

    def _phase_cn(self) -> str:
        phase_map = {
            NIGHT_WEREWOLF: "夜晚·狼人行动",
            NIGHT_SEER: "夜晚·预言家行动",
            NIGHT_WITCH: "夜晚·女巫行动",
            NIGHT_GUARD: "夜晚·守卫行动",
            DAY_ANNOUNCE: "白天·公布死讯",
            DAY_SPEAK: "白天·发言讨论",
            DAY_VOTE: "白天·投票放逐",
            GAME_OVER: "游戏结束",
        }
        return phase_map.get(self.phase, self.phase)

    # ------------------------------------------------------------------
    # HTML visualization
    # ------------------------------------------------------------------

    def get_display_state(self) -> Dict[str, Any]:
        """Return rendered HTML for frontend display."""
        return {"html": self._render_html()}

    def _render_html(self) -> str:
        """Render the game state as a self-contained HTML fragment."""
        phase_cn = self._phase_cn()
        is_night = self.phase.startswith("night_")
        has_human = bool(self.human_roles)
        is_game_over = self.phase == GAME_OVER

        # Background gradient
        bg_gradient = "linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)" if is_night \
            else "linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%)"
        text_color = "#e0e0e0" if is_night else "#333"

        # Phase indicator
        phase_icon = "🌙" if is_night else "☀️"
        if is_game_over:
            phase_icon = "🏆"
            winner_cn = "好人阵营" if self._winner == "good" else "狼人阵营"
            phase_cn = f"游戏结束 — {winner_cn}获胜"

        # Player cards — 3 per row for better readability
        n_players = len(self.players)
        cols = 3 if n_players > 4 else min(4, n_players)
        player_cards = []
        for p in sorted(self.players.values(), key=lambda x: x.seat):
            role_info = ROLE_INFO[p.game_role]
            is_human = p.indexed_role in self.human_roles

            if p.alive:
                card_border = "#4caf50"
                card_bg_p = "rgba(76,175,80,0.15)" if not is_night else "rgba(76,175,80,0.25)"
                if is_human:
                    card_border = "#2196f3"
                    card_bg_p = "rgba(33,150,243,0.2)" if not is_night else "rgba(33,150,243,0.3)"
                icon_display = str(p.seat)
                # Human player sees their own role; game over reveals all
                if is_human or is_game_over:
                    role_display = f'{role_info["icon"]} {role_info["name"]}'
                else:
                    role_display = "???"
            else:
                card_border = "#f44336"
                card_bg_p = "rgba(244,67,54,0.1)"
                icon_display = role_info["icon"]
                role_display = role_info["name"]

            # "你" tag for human player
            human_tag = '<div style="font-size:9px;color:#fff;background:#2196f3;border-radius:3px;padding:0 4px;margin-bottom:2px;">你</div>' if is_human else ''

            # Data attribute for reveal toggle (all alive players get it)
            data_role = f'{role_info["icon"]} {role_info["name"]}' if p.alive else ''
            data_attr = f' data-role="{data_role}"' if data_role else ''

            player_cards.append(
                f'<div style="display:flex;flex-direction:column;align-items:center;'
                f'padding:8px 4px;border-radius:8px;border:2px solid {card_border};'
                f'background:{card_bg_p};min-width:60px;"{data_attr}>'
                f'{human_tag}'
                f'<div style="font-size:20px;font-weight:700;color:{text_color};">{icon_display}</div>'
                f'<div class="role-display" style="font-size:11px;color:{text_color};margin-top:2px;">{role_display}</div>'
                f'<div style="font-size:10px;color:#999;">{p.seat}号</div>'
                f'</div>'
            )

        players_html = (
            f'<div style="display:grid;grid-template-columns:repeat({cols},1fr);gap:8px;'
            f'max-width:{cols * 70}px;margin:0 auto;">'
            + "".join(player_cards)
            + "</div>"
        )

        # "View all identities" button (show whenever game is not over,
        # so observers can peek at AI identities even without a human player)
        # Uses a global function to avoid quote-escaping issues in inline onclick.
        reveal_btn = ""
        if not is_game_over:
            reveal_btn = (
                '<div style="text-align:center;margin-top:8px;">'
                '<button onclick="werewolfReveal(this)"'
                ' style="font-size:11px;padding:4px 12px;border-radius:4px;border:1px solid rgba(128,128,128,0.3);'
                'background:rgba(128,128,128,0.1);color:#999;cursor:pointer;">'
                '👁 查看所有人身份</button></div>'
            )

        # Log (last 8 entries)
        log_html = ""
        recent = self._log[-8:]
        if recent:
            entries = []
            for entry in recent:
                entries.append(
                    f'<div style="font-size:11px;color:#999;padding:1px 0;">'
                    f'R{entry["round"]} {entry["msg"]}</div>'
                )
            log_html = (
                f'<div style="margin-top:10px;border-top:1px solid rgba(128,128,128,0.2);'
                f'padding-top:8px;"><b style="font-size:11px;color:#999;">游戏日志</b>'
                + "".join(entries)
                + "</div>"
            )

        return (
            f'<div style="padding:16px;border-radius:12px;background:{bg_gradient};'
            f'font-family:sans-serif;min-width:280px;">'
            f'<div style="text-align:center;margin-bottom:12px;">'
            f'<span style="font-size:18px;">{phase_icon}</span>'
            f'<span style="font-size:14px;font-weight:600;color:{text_color};margin-left:6px;">'
            f'{phase_cn}</span>'
            f'<span style="font-size:12px;color:#999;margin-left:8px;">第{self.round_num}轮</span>'
            f'</div>'
            f'{players_html}'
            f'{reveal_btn}'
            f'{log_html}'
            f'</div>'
        )
