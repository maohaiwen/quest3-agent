"""Game collaboration mode - simultaneous/sequential strategies with referee judgment"""
import asyncio
import json
import logging
import uuid
from typing import List, Dict, Any, Optional

from app.models.a2a import A2ATask, A2ATaskStatus, A2AMessageRole
from app.models.collaboration import CollaborationResponse, IterationConfig
from app.services.collaboration.base import BaseCollaborationMode
from app.services.collaboration_service import collaboration_service
from app.services.agent_registry import agent_registry

logger = logging.getLogger(__name__)


def _make_sandbox_handler(sandbox, agent_id: str, role: str):
    """Create a closure that routes sandbox tool calls to sandbox.handle_action."""
    async def _handler(action, **kw):
        return await sandbox.handle_action(agent_id, role, action, **kw)
    return _handler


def _anonymize_event(sandbox, event: dict, indexed_role: str) -> dict:
    """If sandbox requests identity anonymization, replace agent_id/role with
    seat-based anonymous names so the chat UI doesn't reveal which AI agent
    is behind which seat (critical for games like Werewolf)."""
    if not sandbox or not getattr(sandbox, 'anonymize_identities', False):
        return event
    identity = sandbox.get_anonymous_identity(indexed_role)
    event = dict(event)  # shallow copy
    if "agent_id" in event:
        event["agent_id"] = identity["agent_id"]
    if "role" in event:
        event["role"] = identity["role"]
    event["display_name"] = identity["display_name"]
    return event


class GameCollaboration(BaseCollaborationMode):
    """Game mode: supports simultaneous and sequential strategies with referee judgment.

    Turn strategies:
    - simultaneous: all participants act at once
    - sequential: participants act in order, one round = all act once

    Referee timing:
    - per_round: referee judges after each round
    - final: referee judges once after all rounds complete

    Sandbox integration:
    - When config_json.sandbox is set, a sandbox environment is created
    - Sandbox injects tools (via A2ATask.sandbox_tools) and state views
    - Sandbox validates actions and checks game-over conditions
    """

    def _get_participants(self, collab: CollaborationResponse) -> list:
        """Get participant agents with their indexed roles"""
        participants = []
        idx = 0
        for agent in collab.agents:
            if agent.role in ("participant", "player_black", "player_white"):
                indexed_role = f"participant_{idx}" if agent.role == "participant" else agent.role
                participants.append((agent, indexed_role, idx))
                idx += 1
        return participants

    def _find_agent_by_role(self, participants, indexed_role):
        """Find the agent config for a given indexed_role."""
        for agent, ir, idx in participants:
            if ir == indexed_role:
                return agent, ir, idx
        return None

    def _get_referee(self, collab: CollaborationResponse):
        """Get referee agent if configured"""
        return next((a for a in collab.agents if a.role == "referee"), None)

    def _init_sandbox(self, config: dict, participants: list):
        """Initialize sandbox if configured. Returns sandbox instance or None."""
        sandbox_name = config.get("sandbox")
        if not sandbox_name:
            return None
        from app.sandboxes.registry import SandboxRegistry
        sandbox = SandboxRegistry.create(sandbox_name, **config.get("sandbox_config", {}))
        if sandbox is None:
            logger.warning(f"Sandbox '{sandbox_name}' not found, proceeding without sandbox")
            return None
        # Map participants to sandbox roles
        agents_info = [{"agent_id": a.agent_id, "role": ir, "is_human": getattr(a, 'is_human', False)} for a, ir, _ in participants]
        sandbox.on_task_start(agents_info)
        logger.info(f"Sandbox '{sandbox_name}' initialized with {len(agents_info)} participants")
        return sandbox

    def _build_participant_prompt(self, collab: CollaborationResponse, input_text: str,
                                   shared_state: dict, role: str, player_index: int,
                                   round_num: int, turn_strategy: str,
                                   round_actions_so_far: list = None,
                                   sandbox = None, agent_id: str = None) -> str:
        """Build prompt for a participant agent.

        Prompt visibility is controlled by config_json.prompt_visibility:
          - "all"         → inject normally (default, backward-compatible)
          - "none"        → do not inject at all
          - "sandbox_only"→ do not inject; sandbox.get_state_view() provides the info
        """
        config = collab.config_json
        game_rules = config.get("game_rules", "")
        custom_instruction = config.get("round_input_template")

        # Read prompt visibility configuration (defaults to "all" for backward compat)
        visibility = config.get("prompt_visibility", {})
        show_input = visibility.get("用户输入", "all")
        show_rules = visibility.get("游戏规则", "all")
        show_custom = visibility.get("上下文指令", "all")
        show_history = visibility.get("历史行动", "all")

        # Component is visible only when set to "all"
        def _vis(setting):
            return setting == "all"

        # State view
        if sandbox and agent_id:
            state_view = sandbox.get_state_view(agent_id, role)
        else:
            state_view = f"当前共享状态：{json.dumps(shared_state, ensure_ascii=False)}"

        # Custom instruction prefix (respects visibility)
        prefix = f"{custom_instruction}\n\n" if (custom_instruction and _vis(show_custom)) else ""

        is_sequential = turn_strategy == "sequential"

        # Sandbox action hint
        action_hint = ""
        if sandbox and agent_id:
            hint = sandbox.get_action_hint(agent_id, role)
            if hint:
                action_hint = f"\n{hint}"

        # Identity line (skip when sandbox provides identity info)
        identity_line = ""
        if not (sandbox and agent_id):
            identity_line = f"\n你是：{role}（第{player_index}位参与者）"

        # Build visibility-controlled sections
        effective_rules = game_rules if game_rules.strip() else input_text

        input_section = f"\n原始任务：{input_text}" if (_vis(show_input) and input_text) else ""
        rules_section = f"\n游戏规则：{effective_rules}" if (_vis(show_rules) and effective_rules) else ""

        earlier_actions = ""
        if is_sequential and _vis(show_history) and round_actions_so_far:
            earlier_actions = f"\n本轮之前参与者的行动：\n" + "\n".join(round_actions_so_far) + "\n"

        game_type = "顺序行动的博弈游戏" if is_sequential else "博弈游戏"
        # When rules are not visible, don't reference them in the closing instruction
        closing = "请严格根据上述游戏规则做出你的行动。" if _vis(show_rules) else "请根据以上信息做出你的行动。"

        if is_sequential:
            return f"""{prefix}你正在参与一个{game_type}。
{rules_section}{input_section}
{state_view}{identity_line}
当前轮次：第{round_num}轮{earlier_actions}
轮到你行动了。

{closing}{action_hint}"""

        return f"""{prefix}你正在参与一个{game_type}。
{rules_section}{input_section}
{state_view}{identity_line}
当前轮次：第{round_num}轮

{closing}{action_hint}"""

    def _build_referee_prompt(self, collab: CollaborationResponse, input_text: str,
                               shared_state: dict, round_actions: str,
                               game_rules: str, is_final: bool = False,
                               sandbox = None) -> str:
        """Build prompt for the referee agent."""
        config = collab.config_json
        custom_instruction = config.get("referee_prompt")

        effective_rules = game_rules if game_rules and game_rules.strip() else input_text

        # If sandbox, include its display state
        if sandbox:
            state_view = sandbox.get_state_view("", "referee")
        else:
            state_view = f"当前共享状态：{json.dumps(shared_state, ensure_ascii=False)}"

        prefix = f"{custom_instruction}\n\n" if custom_instruction else ""

        # When sandbox is present, win/loss is handled by sandbox.check_termination(),
        # so referee only observes/comments. Output is free text, not JSON.
        if sandbox:
            actions_label = "所有轮次的行动记录" if is_final else "本轮各参与者的行动"
            return f"""{prefix}你是游戏观察员。请根据以下信息做简要点评。

游戏规则：{effective_rules}
{state_view}
{actions_label}：
{round_actions}

直接输出文字即可，不要输出JSON。"""

        # No sandbox — referee does full judging with structured JSON
        if is_final:
            return f"""{prefix}你是游戏裁判。所有轮次已经结束，请根据以下信息做出终局裁决。

游戏规则：{effective_rules}
原始任务：{input_text}
{state_view}
所有轮次的行动记录：
{round_actions}

请根据以上信息做出终局裁决，以JSON格式输出：
```json
{{
  "round_result": "终局裁决描述（谁获胜、理由等）",
  "updated_state": {{}},
  "winner": "获胜者角色名",
  "game_over": true
}}
```
其中：
- round_result: 对终局结果的文字描述，包括判定理由
- updated_state: 更新后的共享状态
- winner: 最终获胜者角色名
- game_over: 必须为true

请严格遵守JSON格式输出。"""

        return f"""{prefix}你是游戏裁判。请根据以下信息裁决本轮结果。

游戏规则：{effective_rules}
原始任务：{input_text}
{state_view}
本轮各参与者的行动：
{round_actions}

请根据以上信息做出裁决，以JSON格式输出：
```json
{{
  "round_result": "本轮结果描述（谁赢了、平局等）",
  "updated_state": {{}},
  "winner": null,
  "game_over": false
}}
```
其中：
- round_result: 对本轮结果的文字描述
- updated_state: 更新后的共享状态（保留之前的状态并追加本轮变化）
- winner: 获胜者角色名，如果尚未决出则填null
- game_over: 游戏是否结束（true/false）

请严格遵守JSON格式输出。"""

    @staticmethod
    def _parse_referee_output(output: str) -> dict:
        """Parse referee's structured JSON output"""
        text = output.strip()

        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start) if "```" in text[start:] else len(text)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start) if "```" in text[start:] else len(text)
            text = text[start:end].strip()

        try:
            result = json.loads(text)
            return {
                "round_result": result.get("round_result", ""),
                "updated_state": result.get("updated_state", {}),
                "winner": result.get("winner"),
                "game_over": bool(result.get("game_over", False))
            }
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse referee output as JSON: {output[:200]}")
            return {
                "round_result": output,
                "updated_state": {},
                "winner": None,
                "game_over": False
            }

    @staticmethod
    def _resolve_turn_strategy(config: dict) -> str:
        """Resolve turn strategy with backward compatibility for 'turn_based'"""
        strategy = config.get("turn_strategy", "simultaneous")
        if strategy == "turn_based":
            strategy = "sequential"
        return strategy

    def _build_order_map(self, participants, participant_order, config):
        """Build participant order for sequential mode"""
        if not participant_order:
            participant_order = [p[1] for p in participants]
        order_map = {}
        for agent, indexed_role, idx in participants:
            order_map[indexed_role] = agent
            order_map[agent.role] = agent
        return order_map, participant_order

    async def _execute_round_simultaneous(self, collab, input_text, shared_state,
                                            participants, round_num, turn_strategy, task,
                                            sandbox=None):
        """Execute one round with simultaneous strategy"""
        tasks = []
        for agent, indexed_role, idx in participants:
            prompt = self._build_participant_prompt(
                collab, input_text, shared_state, indexed_role, idx, round_num, turn_strategy,
                sandbox=sandbox, agent_id=agent.agent_id)
            t = A2ATask(id=str(uuid.uuid4()), input=prompt)
            # Inject sandbox tools
            if sandbox:
                t.sandbox_tools = sandbox.get_tools_for_llm(agent.agent_id, indexed_role)
                t.sandbox_handler = _make_sandbox_handler(sandbox, agent.agent_id, indexed_role)
            tasks.append((agent, indexed_role, idx, t))

        results = await asyncio.gather(
            *[agent_registry.call_agent(a.agent_id, t) for a, _, _, t in tasks],
            return_exceptions=True
        )

        round_actions = []
        for i, result in enumerate(results):
            agent, indexed_role, idx, _ = tasks[i]
            if isinstance(result, Exception):
                action = f"[{indexed_role} failed: {str(result)}]"
            else:
                action = result.output or ""
            round_actions.append(f"{indexed_role}: {action}")
            task.add_message(A2AMessageRole.AGENT,
                             f"[Round {round_num}] {indexed_role}: {action}")

        return round_actions

    async def _execute_round_sequential(self, collab, input_text, shared_state,
                                          participants, participant_order, order_map,
                                          round_num, turn_strategy, task,
                                          sandbox=None):
        """Execute one round with sequential strategy"""
        round_actions = []
        round_actions_so_far = []

        for role_key in participant_order:
            agent = order_map.get(role_key)
            if not agent:
                raise ValueError(f"No agent found for role: {role_key}")

            idx = next((i for a, r, i in participants if r == role_key or a.role == role_key), 0)

            prompt = self._build_participant_prompt(
                collab, input_text, shared_state, role_key, idx, round_num,
                turn_strategy, round_actions_so_far,
                sandbox=sandbox, agent_id=agent.agent_id)

            agent_task = A2ATask(id=str(uuid.uuid4()), input=prompt)
            # Inject sandbox tools
            if sandbox:
                agent_task.sandbox_tools = sandbox.get_tools_for_llm(agent.agent_id, role_key)
                agent_task.sandbox_handler = _make_sandbox_handler(sandbox, agent.agent_id, role_key)

            result = await agent_registry.call_agent(agent.agent_id, agent_task)

            action = result.output or ""
            action_line = f"{role_key}: {action}"
            round_actions.append(action_line)
            round_actions_so_far.append(action_line)
            task.add_message(A2AMessageRole.AGENT,
                             f"[Round {round_num}] {role_key}: {action}")

        # Store this round's actions in shared_state for later rounds
        shared_state[f"round_{round_num}_actions"] = round_actions_so_far
        return round_actions

    def _apply_ruling(self, task, ruling, round_num, is_final: bool = False):
        """Apply referee ruling to task state, return True if game is over"""
        if ruling["game_over"] or is_final:
            winner = ruling.get("winner")
            prefix = "终局裁决：" if is_final else ""
            result_msg = ruling["round_result"]
            if winner:
                task.set_completed(f"{prefix}{winner} 获胜！{result_msg}")
            else:
                task.set_completed(f"{prefix}游戏结束。{result_msg}")
            task.add_message(A2AMessageRole.AGENT, f"{'终局裁决' if is_final else '游戏结束'}: {result_msg}")
            return True

        return False

    async def execute(self, collab: CollaborationResponse, input_text: str) -> A2ATask:
        task = self._create_task(input_text)
        await self._create_task_record(collab.id, task)

        try:
            config = collab.config_json
            turn_strategy = self._resolve_turn_strategy(config)
            referee_timing = config.get("referee_timing", "per_round")
            max_rounds = config.get("max_rounds", 10)
            game_rules = config.get("game_rules", "")
            shared_state = dict(config.get("shared_state", {}))
            referee_enabled = config.get("referee_enabled", True)
            participant_order = config.get("participant_order", [])

            participants = self._get_participants(collab)
            referee_agent = self._get_referee(collab)

            if not participants:
                raise ValueError("No participant agents found in collaboration")
            if referee_enabled and not referee_agent:
                raise ValueError("Referee is enabled but no referee agent found")

            # Initialize sandbox
            sandbox = self._init_sandbox(config, participants)

            if turn_strategy == "sequential":
                order_map, participant_order = self._build_order_map(
                    participants, participant_order, config)

            task.add_message(A2AMessageRole.USER, f"Game start: {input_text}")

            all_round_actions = []

            for round_num in range(1, max_rounds + 1):
                logger.info(f"Game round {round_num}/{max_rounds} (strategy: {turn_strategy})")

                if turn_strategy == "simultaneous":
                    round_actions = await self._execute_round_simultaneous(
                        collab, input_text, shared_state, participants,
                        round_num, turn_strategy, task, sandbox=sandbox)
                else:
                    round_actions = await self._execute_round_sequential(
                        collab, input_text, shared_state, participants,
                        participant_order, order_map, round_num, turn_strategy, task,
                        sandbox=sandbox)

                all_round_actions.append((round_num, round_actions))

                # Store actions in shared state
                for action_line in round_actions:
                    role_part = action_line.split(":")[0].strip()
                    shared_state[f"round_{round_num}_{role_part}_output"] = action_line

                # Check sandbox termination first
                if sandbox:
                    term = sandbox.check_termination()
                    if term and term.get("game_over"):
                        winner = term.get("winner")
                        reason = term.get("reason", "游戏结束")
                        if winner:
                            task.set_completed(f"游戏结束，{winner} 获胜！{reason}")
                        else:
                            task.set_completed(f"游戏结束。{reason}")
                        task.add_message(A2AMessageRole.AGENT, f"游戏结束: {reason}")
                        break

                # Referee per round
                if referee_enabled and referee_agent and referee_timing == "per_round":
                    referee_prompt = self._build_referee_prompt(
                        collab, input_text, shared_state,
                        "\n".join(round_actions), game_rules, sandbox=sandbox)
                    referee_task = A2ATask(id=str(uuid.uuid4()), input=referee_prompt)
                    referee_result = await agent_registry.call_agent(referee_agent.agent_id, referee_task)

                    ruling = self._parse_referee_output(referee_result.output or "")
                    task.add_message(A2AMessageRole.AGENT,
                                     f"[Round {round_num}] Referee: {ruling['round_result']}")

                    if ruling["updated_state"]:
                        shared_state.update(ruling["updated_state"])
                    shared_state[f"round_{round_num}_result"] = ruling["round_result"]

                    if self._apply_ruling(task, ruling, round_num):
                        break
            else:
                # All rounds completed
                if referee_enabled and referee_agent and referee_timing == "final":
                    all_actions_text = "\n".join(
                        f"--- Round {rn} ---\n" + "\n".join(actions)
                        for rn, actions in all_round_actions
                    )
                    referee_prompt = self._build_referee_prompt(
                        collab, input_text, shared_state,
                        all_actions_text, game_rules, is_final=True, sandbox=sandbox)
                    referee_task = A2ATask(id=str(uuid.uuid4()), input=referee_prompt)
                    referee_result = await agent_registry.call_agent(referee_agent.agent_id, referee_task)

                    ruling = self._parse_referee_output(referee_result.output or "")
                    task.add_message(A2AMessageRole.AGENT,
                                     f"[Final] Referee: {ruling['round_result']}")

                    if ruling["updated_state"]:
                        shared_state.update(ruling["updated_state"])

                    self._apply_ruling(task, ruling, round_num, is_final=True)
                else:
                    result_msg = f"达到最大轮次 {max_rounds}，游戏结束"
                    task.set_completed(result_msg)
                    task.add_message(A2AMessageRole.AGENT, result_msg)

            if sandbox:
                sandbox.on_task_end()

            await self._update_task_record(task, completed=True)
            await collaboration_service.increment_usage(collab.id)
            return task

        except Exception as e:
            logger.error(f"Game collaboration failed: {e}", exc_info=True)
            task.set_failed(str(e))
            await self._update_task_record(task, completed=True)
            return task

    async def execute_stream(self, collab: CollaborationResponse, input_text: str):
        """Execute game mode with SSE event streaming"""
        task = self._create_task(input_text)
        if not self._skip_task_record:
            await self._create_task_record(collab.id, task)

        try:
            tid = self._shared_task_id or task.id
            yield {
                "type": "task_start",
                "task_id": tid,
                "input": input_text,
                "mode": "game"
            }

            config = collab.config_json
            turn_strategy = self._resolve_turn_strategy(config)
            referee_timing = config.get("referee_timing", "per_round")
            max_rounds = config.get("max_rounds", 10)
            game_rules = config.get("game_rules", "")
            shared_state = dict(config.get("shared_state", {}))
            referee_enabled = config.get("referee_enabled", True)
            participant_order = config.get("participant_order", [])

            participants = self._get_participants(collab)
            referee_agent = self._get_referee(collab)

            if not participants:
                yield {"type": "task_failed", "error": "No participant agents found"}
                return

            if referee_enabled and not referee_agent:
                yield {"type": "task_failed", "error": "Referee is enabled but no referee agent found"}
                return

            # Initialize sandbox
            sandbox = self._init_sandbox(config, participants)
            sandbox_name = config.get("sandbox", "")

            if turn_strategy == "sequential":
                order_map, participant_order = self._build_order_map(
                    participants, participant_order, config)

            # Build participants list — anonymize if sandbox requests it
            participants_list = [p[1] for p in participants]
            if sandbox and getattr(sandbox, 'anonymize_identities', False):
                participants_list = [
                    sandbox.get_anonymous_identity(ir)["agent_id"]
                    for ir in participants_list
                ]

            yield {
                "type": "game_start",
                "shared_state": shared_state,
                "participants": participants_list,
                "turn_strategy": turn_strategy,
                "referee_enabled": referee_enabled,
                "sandbox": sandbox_name,
            }

            # Emit initial sandbox state
            if sandbox:
                yield {
                    "type": "sandbox_state",
                    "sandbox": sandbox_name,
                    "state": sandbox.get_display_state(),
                }

            task.add_message(A2AMessageRole.USER, f"Game start: {input_text}")

            all_round_actions = []

            for round_num in range(1, max_rounds + 1):
                yield {"type": "round_start", "round": round_num, "max_rounds": max_rounds}

                round_actions = []

                # ---- Sandbox-driven sub-phase flow ----
                if sandbox and getattr(sandbox, 'supports_sub_phases', False):
                    sandbox_round_start = getattr(sandbox, 'round_num', round_num)
                    sub_phase_done = False
                    while not sub_phase_done:
                        active = sandbox.get_active_participants()
                        if not active:
                            break  # No more active agents — sub-phase flow complete

                        # Emit phase info
                        phase_desc = sandbox.get_phase_description()
                        yield {"type": "sandbox_phase", "phase": phase_desc, "round": round_num}

                        # Prompt each active participant sequentially
                        for item in active:
                            indexed_role = item[0]
                            agent_info = self._find_agent_by_role(participants, indexed_role)
                            if not agent_info:
                                continue
                            agent, ir, idx = agent_info

                            # ---- Human participant branch ----
                            if agent.is_human:
                                # Capture phase BEFORE action — sandbox action handlers
                                # (e.g. guard's _resolve_night) may transition the phase,
                                # which would cause record_speech to record a night action
                                # as a day speech.
                                phase_before_action = sandbox.phase if sandbox else None
                                state_view = sandbox.get_state_view("human", indexed_role) if sandbox else ""
                                is_private = sandbox and sandbox.is_private_phase()
                                suppress_human_events = is_private and getattr(sandbox, 'anonymize_identities', False)

                                # Always emit agent_start/agent_done so the
                                # frontend panel lifecycle stays consistent;
                                # anonymization hides the identity
                                yield _anonymize_event(sandbox, {
                                    "type": "agent_start",
                                    "agent_id": "human",
                                    "role": indexed_role,
                                    "round": round_num
                                }, indexed_role)

                                # waiting_for_human must always be emitted (so the
                                # frontend shows the input panel), but in private
                                # phases mark it as private so the chat stream
                                # hides the identity (the state_view is still
                                # shown in the input panel, not the chat stream)
                                yield _anonymize_event(sandbox, {
                                    "type": "waiting_for_human",
                                    "role": indexed_role,
                                    "round": round_num,
                                    "state_view": state_view,
                                    "private": suppress_human_events,
                                }, indexed_role)

                                yield {
                                    "type": "sandbox_state",
                                    "sandbox": sandbox_name,
                                    "state": sandbox.get_display_state(),
                                }
                                result = await self._wait_for_human_input(
                                    task.id, "human", indexed_role,
                                    sandbox=sandbox, prompt=state_view,
                                )
                                while not result.get("success"):
                                    if result.get("error") in ("等待人类输入超时", "输入已取消"):
                                        yield {"type": "task_failed", "error": result["error"]}
                                        sub_phase_done = True
                                        break
                                    yield _anonymize_event(sandbox, {
                                        "type": "human_move_error",
                                        "role": indexed_role,
                                        "error": result.get("error", "无效操作"),
                                    }, indexed_role)
                                    state_view = sandbox.get_state_view("human", indexed_role)
                                    result = await self._wait_for_human_input(
                                        task.id, "human", indexed_role,
                                        sandbox=sandbox, prompt=state_view,
                                    )
                                if sub_phase_done:
                                    break
                                action = result.get("message", "")
                                # Always emit human_moved so the frontend hides
                                # the input panel; in private phases, strip
                                # the result details to avoid leaking info
                                yield _anonymize_event(sandbox, {
                                    "type": "human_moved",
                                    "role": indexed_role,
                                    "round": round_num,
                                    "result": {} if suppress_human_events else result,
                                }, indexed_role)
                                action_line = f"{indexed_role}: {action}"
                                round_actions.append(action_line)
                                # Record speech in sandbox if applicable
                                # Use phase_before_action (captured before the action was
                                # processed) to avoid recording night actions as day speeches
                                # when _resolve_night() transitions the phase to day_speak.
                                if hasattr(sandbox, 'record_speech') and phase_before_action == "day_speak":
                                    sandbox.record_speech(indexed_role, action)
                                # Always emit agent_done so frontend cleans up
                                yield _anonymize_event(sandbox, {"type": "agent_done", "agent_id": "human", "role": indexed_role, "round": round_num}, indexed_role)
                                yield {
                                    "type": "sandbox_state",
                                    "sandbox": sandbox_name,
                                    "state": sandbox.get_display_state(),
                                }

                            # ---- AI participant branch ----
                            else:
                                # Capture phase BEFORE action — sandbox action handlers
                                # (e.g. guard's _resolve_night) may transition the phase,
                                # which would cause record_speech to record a night action
                                # as a day speech.
                                phase_before_action = sandbox.phase if sandbox else None

                                prompt = self._build_participant_prompt(
                                    collab, input_text, shared_state, indexed_role, idx, round_num, "sequential",
                                    sandbox=sandbox, agent_id=agent.agent_id)

                                # In private phases of anonymized sandboxes (e.g.
                                # werewolf night), completely suppress AI events
                                # so the viewer cannot infer who is acting.
                                is_private = sandbox and sandbox.is_private_phase()
                                suppress_ai_events = is_private and getattr(sandbox, 'anonymize_identities', False)

                                if not suppress_ai_events:
                                    yield _anonymize_event(sandbox, {
                                        "type": "agent_start",
                                        "agent_id": agent.agent_id,
                                        "role": indexed_role,
                                        "round": round_num
                                    }, indexed_role)

                                agent_task = A2ATask(id=str(uuid.uuid4()), input=prompt)
                                agent_task.sandbox_tools = sandbox.get_tools_for_llm(agent.agent_id, indexed_role)
                                agent_task.sandbox_handler = _make_sandbox_handler(sandbox, agent.agent_id, indexed_role)

                                # When a human participant is present and the
                                # current phase is private (e.g. werewolf
                                # night), suppress detailed AI events so the
                                # human doesn't see other players' actions.
                                has_human = any(a.is_human for a, _, _ in participants)
                                hide_ai_detail = has_human and sandbox.is_private_phase()

                                action = ""
                                async for sub_event in agent_registry.call_agent_stream(agent.agent_id, agent_task):
                                    etype = sub_event.get("type")
                                    # Always capture content for action text
                                    if etype == "content":
                                        action += sub_event["content"]
                                    # In private phases, suppress all AI events
                                    if suppress_ai_events:
                                        continue
                                    # When human is present in private phase,
                                    # suppress detailed events (thinking, content, etc.)
                                    if hide_ai_detail and etype not in ("done",):
                                        continue
                                    yield _anonymize_event(sandbox, {
                                        "type": f"agent_{etype}",
                                        "agent_id": agent.agent_id,
                                        "role": indexed_role,
                                        "round": round_num,
                                        **{k: v for k, v in sub_event.items() if k != "type"},
                                    }, indexed_role)

                                if not action and agent_task.output:
                                    action = agent_task.output

                                action_line = f"{indexed_role}: {action}"
                                round_actions.append(action_line)
                                # Record speech in sandbox if applicable
                                # Use phase_before_action (captured before the action was
                                # processed) to avoid recording night actions as day speeches
                                # when _resolve_night() transitions the phase to day_speak.
                                if hasattr(sandbox, 'record_speech') and phase_before_action == "day_speak":
                                    sandbox.record_speech(indexed_role, action)

                                if not suppress_ai_events:
                                    yield _anonymize_event(sandbox, {"type": "agent_done", "agent_id": agent.agent_id, "role": indexed_role, "round": round_num}, indexed_role)
                                yield {
                                    "type": "sandbox_state",
                                    "sandbox": sandbox_name,
                                    "state": sandbox.get_display_state(),
                                }

                            # Check termination after each action
                            if sandbox.check_termination():
                                sub_phase_done = True
                                break

                        # Check if the sandbox round changed (e.g. day vote → new night)
                        if not sub_phase_done:
                            current_sandbox_round = getattr(sandbox, 'round_num', round_num)
                            if current_sandbox_round != sandbox_round_start:
                                sub_phase_done = True  # Round complete

                elif turn_strategy == "simultaneous":
                    # Parallel streaming using queue
                    game_tasks = []
                    for agent, indexed_role, idx in participants:
                        prompt = self._build_participant_prompt(
                            collab, input_text, shared_state, indexed_role, idx, round_num, turn_strategy,
                            sandbox=sandbox, agent_id=agent.agent_id)
                        t = A2ATask(id=str(uuid.uuid4()), input=prompt)
                        # Inject sandbox tools
                        if sandbox:
                            t.sandbox_tools = sandbox.get_tools_for_llm(agent.agent_id, indexed_role)
                            t.sandbox_handler = _make_sandbox_handler(sandbox, agent.agent_id, indexed_role)
                        game_tasks.append((agent, indexed_role, idx, t))

                    # Suppress agent_start in private phases of anonymized sandboxes
                    is_sim_private = sandbox and sandbox.is_private_phase()
                    suppress_sim_events = is_sim_private and getattr(sandbox, 'anonymize_identities', False)

                    if not suppress_sim_events:
                        for agent, indexed_role, idx, _ in game_tasks:
                            yield _anonymize_event(sandbox, {
                                "type": "agent_start",
                                "agent_id": agent.agent_id,
                                "role": indexed_role,
                                "round": round_num
                            }, indexed_role)

                    event_queue: asyncio.Queue = asyncio.Queue()

                    async def _run_participant_stream(agent, indexed_role, g_task, round_num):
                        output = ""
                        try:
                            async for sub_event in agent_registry.call_agent_stream(agent.agent_id, g_task):
                                # In private phases of anonymized sandboxes, suppress
                                # all AI events to avoid revealing who is acting
                                if suppress_sim_events:
                                    pass
                                else:
                                    await event_queue.put(_anonymize_event(sandbox, {
                                        "type": f"agent_{sub_event['type']}",
                                        "agent_id": agent.agent_id,
                                        "role": indexed_role,
                                        "round": round_num,
                                        **{k: v for k, v in sub_event.items() if k != "type"},
                                    }, indexed_role))
                                if sub_event.get("type") == "content":
                                    output += sub_event["content"]
                        except Exception as e:
                            if not suppress_sim_events:
                                await event_queue.put({
                                    "type": "agent_error",
                                    "agent_id": agent.agent_id,
                                    "message": str(e),
                                })
                        if not output and g_task.output:
                            output = g_task.output
                        await event_queue.put({"type": "_participant_done", "agent_id": agent.agent_id, "indexed_role": indexed_role, "output": output})

                    async_tasks = [
                        asyncio.create_task(_run_participant_stream(a, ir, t, round_num))
                        for a, ir, _, t in game_tasks
                    ]

                    done_count = 0
                    participant_outputs = {}
                    sandbox_terminated = False
                    while done_count < len(game_tasks):
                        event = await event_queue.get()
                        if event["type"] == "_participant_done":
                            done_count += 1
                            participant_outputs[event["agent_id"]] = (event["indexed_role"], event["output"])
                            round_actions.append(f"{event['indexed_role']}: {event['output']}")
                            if not suppress_sim_events:
                                yield _anonymize_event(sandbox, {"type": "agent_done", "agent_id": event["agent_id"], "role": event["indexed_role"], "round": round_num}, event["indexed_role"])
                            # Emit sandbox state immediately after each participant finishes
                            if sandbox and not sandbox_terminated:
                                yield {
                                    "type": "sandbox_state",
                                    "sandbox": sandbox_name,
                                    "state": sandbox.get_display_state(),
                                }
                                # Check if sandbox says game over (e.g. king captured)
                                term = sandbox.check_termination()
                                if term and term.get("game_over"):
                                    sandbox_terminated = True
                        else:
                            yield event

                    await asyncio.gather(*async_tasks, return_exceptions=True)

                else:  # sequential — stream directly
                    round_actions_so_far = []
                    for role_key in participant_order:
                        agent = order_map.get(role_key)
                        if not agent:
                            yield {"type": "task_failed", "error": f"No agent found for role: {role_key}"}
                            return

                        idx = next((i for a, r, i in participants if r == role_key or a.role == role_key), 0)

                        # ---- Human participant branch ----
                        if agent.is_human:
                            state_view = sandbox.get_state_view("human", role_key) if sandbox else "请输入你的行动"
                            yield {
                                "type": "agent_start",
                                "agent_id": "human",
                                "role": role_key,
                                "round": round_num
                            }
                            yield {
                                "type": "waiting_for_human",
                                "role": role_key,
                                "round": round_num,
                                "state_view": state_view,
                            }

                            if sandbox:
                                yield {
                                    "type": "sandbox_state",
                                    "sandbox": sandbox_name,
                                    "state": sandbox.get_display_state(),
                                }
                                result = await self._wait_for_human_input(
                                    task.id, "human", role_key,
                                    sandbox=sandbox, prompt=state_view,
                                )
                            else:
                                result = await self._wait_for_human_input(
                                    task.id, "human", role_key,
                                    prompt="请输入你的行动",
                                )

                            # If invalid move (sandbox rejected), re-wait until valid or timeout
                            while not result.get("success"):
                                # Timeout or cancellation — break out
                                if result.get("error") in ("等待人类输入超时", "输入已取消"):
                                    yield {"type": "task_failed", "error": result["error"]}
                                    return
                                yield {
                                    "type": "human_move_error",
                                    "role": role_key,
                                    "error": result.get("error", "无效操作"),
                                }
                                if sandbox:
                                    state_view = sandbox.get_state_view("human", role_key)
                                    result = await self._wait_for_human_input(
                                        task.id, "human", role_key,
                                        sandbox=sandbox, prompt=state_view,
                                    )
                                else:
                                    result = await self._wait_for_human_input(
                                        task.id, "human", role_key,
                                        prompt="请重新输入",
                                    )

                            action = result.get("message", "")
                            yield {
                                "type": "human_moved",
                                "role": role_key,
                                "round": round_num,
                                "result": result,
                            }

                            action_line = f"{role_key}: {action}"
                            round_actions.append(action_line)
                            round_actions_so_far.append(action_line)

                            yield {"type": "agent_done", "agent_id": "human", "role": role_key, "round": round_num}

                            if sandbox:
                                yield {
                                    "type": "sandbox_state",
                                    "sandbox": sandbox_name,
                                    "state": sandbox.get_display_state(),
                                }

                        # ---- AI participant branch (original logic) ----
                        else:
                            prompt = self._build_participant_prompt(
                                collab, input_text, shared_state, role_key, idx, round_num,
                                turn_strategy, round_actions_so_far,
                                sandbox=sandbox, agent_id=agent.agent_id)

                            yield {
                                "type": "agent_start",
                                "agent_id": agent.agent_id,
                                "role": role_key,
                                "round": round_num
                            }

                            agent_task = A2ATask(id=str(uuid.uuid4()), input=prompt)
                            # Inject sandbox tools
                            if sandbox:
                                agent_task.sandbox_tools = sandbox.get_tools_for_llm(agent.agent_id, role_key)
                                agent_task.sandbox_handler = _make_sandbox_handler(sandbox, agent.agent_id, role_key)

                            # Suppress detailed AI events in private phases when a
                            # human participant is present
                            has_human = any(a.is_human for a, _, _ in participants)
                            hide_ai_detail = sandbox and has_human and sandbox.is_private_phase()

                            action = ""

                            async for sub_event in agent_registry.call_agent_stream(agent.agent_id, agent_task):
                                etype = sub_event.get("type")
                                if etype == "content":
                                    action += sub_event["content"]
                                if hide_ai_detail and etype not in ("done",):
                                    continue
                                yield {
                                    "type": f"agent_{etype}",
                                    "agent_id": agent.agent_id,
                                    "role": role_key,
                                    "round": round_num,
                                    **{k: v for k, v in sub_event.items() if k != "type"},
                                }

                            if not action and agent_task.output:
                                action = agent_task.output

                            action_line = f"{role_key}: {action}"
                            round_actions.append(action_line)
                            round_actions_so_far.append(action_line)

                            yield {"type": "agent_done", "agent_id": agent.agent_id, "role": role_key, "round": round_num}

                            # Emit sandbox state immediately after each participant finishes
                            if sandbox:
                                yield {
                                    "type": "sandbox_state",
                                    "sandbox": sandbox_name,
                                    "state": sandbox.get_display_state(),
                                }

                    shared_state[f"round_{round_num}_actions"] = round_actions_so_far

                all_round_actions.append((round_num, round_actions))

                # Store actions in shared state
                # When sandbox is present, we skip storing individual player
                # action text in shared_state because it contains private info
                # (e.g. "我是守卫（座位号5）" during night).  The sandbox
                # handles per-player visibility via get_state_view() instead.
                if not sandbox:
                    for action_line in round_actions:
                        role_part = action_line.split(":")[0].strip()
                        content_part = ":".join(action_line.split(":")[1:]).strip()
                        shared_state[f"round_{round_num}_{role_part}_output"] = content_part

                # Check sandbox termination first (before referee)
                if sandbox:
                    term = sandbox.check_termination()
                    if term and term.get("game_over"):
                        winner = term.get("winner")
                        reason = term.get("reason", "游戏结束")
                        if winner:
                            task.set_completed(f"游戏结束，{winner} 获胜！{reason}")
                        else:
                            task.set_completed(f"游戏结束。{reason}")
                        task.add_message(A2AMessageRole.AGENT, f"游戏结束: {reason}")

                        yield {
                            "type": "shared_state_update",
                            "shared_state": shared_state,
                            "round": round_num,
                        }
                        yield {
                            "type": "round_end",
                            "round": round_num,
                            "passed": False,
                            "round_result": reason,
                            "winner": winner,
                            "game_over": True,
                        }
                        yield {
                            "type": "termination",
                            "round": round_num,
                            "message": reason,
                            "winner": winner,
                        }
                        break

                # Referee per round (streaming)
                if referee_enabled and referee_agent and referee_timing == "per_round":
                    yield {
                        "type": "agent_start",
                        "agent_id": referee_agent.agent_id,
                        "role": "referee",
                        "round": round_num
                    }

                    referee_prompt = self._build_referee_prompt(
                        collab, input_text, shared_state,
                        "\n".join(round_actions), game_rules, sandbox=sandbox)
                    referee_task = A2ATask(id=str(uuid.uuid4()), input=referee_prompt)
                    referee_output = ""

                    async for sub_event in agent_registry.call_agent_stream(referee_agent.agent_id, referee_task):
                        yield {
                            "type": f"agent_{sub_event['type']}",
                            "agent_id": referee_agent.agent_id,
                            "role": "referee",
                            "round": round_num,
                            **{k: v for k, v in sub_event.items() if k != "type"},
                        }
                        if sub_event.get("type") == "content":
                            referee_output += sub_event["content"]

                    if not referee_output and referee_task.output:
                        referee_output = referee_task.output

                    ruling = self._parse_referee_output(referee_output)

                    yield {"type": "agent_done", "agent_id": referee_agent.agent_id, "role": "referee", "round": round_num}

                    if ruling["updated_state"]:
                        shared_state.update(ruling["updated_state"])
                    shared_state[f"round_{round_num}_result"] = ruling["round_result"]

                    yield {"type": "shared_state_update", "shared_state": shared_state, "round": round_num}

                    yield {
                        "type": "round_end",
                        "round": round_num,
                        "passed": not ruling["game_over"],
                        "round_result": ruling["round_result"],
                        "winner": ruling.get("winner"),
                        "game_over": ruling["game_over"]
                    }

                    if ruling["game_over"]:
                        winner = ruling.get("winner")
                        result_msg = ruling["round_result"]
                        if winner:
                            task.set_completed(f"游戏结束，{winner} 获胜！{result_msg}")
                        else:
                            task.set_completed(f"游戏结束。{result_msg}")
                        task.add_message(A2AMessageRole.AGENT, f"游戏结束: {result_msg}")

                        yield {
                            "type": "termination",
                            "round": round_num,
                            "message": result_msg,
                            "winner": winner
                        }
                        break
                else:
                    yield {"type": "shared_state_update", "shared_state": shared_state, "round": round_num}
                    yield {"type": "round_end", "round": round_num, "passed": True}
            else:
                # All rounds completed — final referee (streaming)
                if referee_enabled and referee_agent and referee_timing == "final":
                    yield {
                        "type": "agent_start",
                        "agent_id": referee_agent.agent_id,
                        "role": "referee",
                        "round": max_rounds
                    }

                    all_actions_text = "\n".join(
                        f"--- Round {rn} ---\n" + "\n".join(actions)
                        for rn, actions in all_round_actions
                    )
                    referee_prompt = self._build_referee_prompt(
                        collab, input_text, shared_state,
                        all_actions_text, game_rules, is_final=True, sandbox=sandbox)
                    referee_task = A2ATask(id=str(uuid.uuid4()), input=referee_prompt)
                    referee_output = ""

                    async for sub_event in agent_registry.call_agent_stream(referee_agent.agent_id, referee_task):
                        yield {
                            "type": f"agent_{sub_event['type']}",
                            "agent_id": referee_agent.agent_id,
                            "role": "referee",
                            "round": max_rounds,
                            **{k: v for k, v in sub_event.items() if k != "type"},
                        }
                        if sub_event.get("type") == "content":
                            referee_output += sub_event["content"]

                    if not referee_output and referee_task.output:
                        referee_output = referee_task.output

                    ruling = self._parse_referee_output(referee_output)

                    yield {"type": "agent_done", "agent_id": referee_agent.agent_id, "role": "referee", "round": max_rounds}

                    if ruling["updated_state"]:
                        shared_state.update(ruling["updated_state"])

                    yield {"type": "shared_state_update", "shared_state": shared_state, "round": max_rounds}

                    winner = ruling.get("winner")
                    if winner:
                        task.set_completed(f"终局裁决：{winner} 获胜！{ruling['round_result']}")
                    else:
                        task.set_completed(f"终局裁决：{ruling['round_result']}")
                    task.add_message(A2AMessageRole.AGENT, f"终局裁决: {ruling['round_result']}")

                    yield {
                        "type": "termination",
                        "round": max_rounds,
                        "message": ruling["round_result"],
                        "winner": winner
                    }
                else:
                    result_msg = f"达到最大轮次 {max_rounds}，游戏结束"
                    task.set_completed(result_msg)
                    task.add_message(A2AMessageRole.AGENT, result_msg)

            if sandbox:
                sandbox.on_task_end()

            if not self._skip_task_record:
                await self._update_task_record(task, completed=True)
                await collaboration_service.increment_usage(collab.id)

            yield {
                "type": "task_complete",
                "task_id": task.id,
                "status": task.status.state.value,
                "output": task.output,
                "messages": [m.dict() for m in task.messages]
            }

        except Exception as e:
            logger.error(f"Game collaboration failed: {e}", exc_info=True)
            task.set_failed(str(e))
            if not self._skip_task_record:
                await self._update_task_record(task, completed=True)
            yield {"type": "task_failed", "task_id": task.id, "error": str(e)}
