"""Game collaboration mode - simultaneous/sequential strategies with referee judgment"""
import asyncio
import json
import logging
import uuid
from typing import List, Dict, Any

from app.models.a2a import A2ATask, A2ATaskStatus, A2ATaskStatusState, A2AMessage, A2AMessageRole
from app.models.collaboration import CollaborationResponse
from app.services.collaboration.base import BaseCollaborationMode
from app.services.collaboration_service import collaboration_service
from app.services.agent_registry import agent_registry

logger = logging.getLogger(__name__)


class GameCollaboration(BaseCollaborationMode):
    """Game mode: supports simultaneous and sequential strategies with referee judgment.

    Turn strategies:
    - simultaneous: all participants act at once
    - sequential: participants act in order, one round = all act once

    Referee timing:
    - per_round: referee judges after each round
    - final: referee judges once after all rounds complete
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

    def _get_referee(self, collab: CollaborationResponse):
        """Get referee agent if configured"""
        return next((a for a in collab.agents if a.role == "referee"), None)

    def _build_participant_prompt(self, collab: CollaborationResponse, input_text: str,
                                   shared_state: dict, role: str, player_index: int,
                                   round_num: int, turn_strategy: str,
                                   round_actions_so_far: list = None) -> str:
        """Build prompt for a participant agent."""
        config = collab.config_json
        game_rules = config.get("game_rules", "")
        custom_instruction = config.get("round_input_template")

        effective_rules = game_rules if game_rules.strip() else input_text
        shared_state_str = json.dumps(shared_state, ensure_ascii=False)

        prefix = f"{custom_instruction}\n\n" if custom_instruction else ""
        is_sequential = turn_strategy == "sequential"

        if is_sequential:
            earlier_actions = ""
            if round_actions_so_far:
                earlier_actions = f"\n本轮之前参与者的行动：\n" + "\n".join(round_actions_so_far) + "\n"

            return f"""{prefix}你正在参与一个顺序行动的博弈游戏。

游戏规则：{effective_rules}
原始任务：{input_text}
当前共享状态：{shared_state_str}
你是：{role}（第{player_index}位参与者）
当前轮次：第{round_num}轮{earlier_actions}
轮到你行动了。

请严格根据上述游戏规则做出你的行动。只输出你的行动，不要输出其他内容。"""

        return f"""{prefix}你正在参与一个博弈游戏。

游戏规则：{effective_rules}
原始任务：{input_text}
当前共享状态：{shared_state_str}
你是：{role}（第{player_index}位参与者）
当前轮次：第{round_num}轮

请严格根据上述游戏规则做出你的行动。只输出你的行动，不要输出其他内容。"""

    def _build_referee_prompt(self, collab: CollaborationResponse, input_text: str,
                               shared_state: dict, round_actions: str,
                               game_rules: str, is_final: bool = False) -> str:
        """Build prompt for the referee agent."""
        config = collab.config_json
        custom_instruction = config.get("referee_prompt")

        effective_rules = game_rules if game_rules and game_rules.strip() else input_text
        shared_state_str = json.dumps(shared_state, ensure_ascii=False)
        prefix = f"{custom_instruction}\n\n" if custom_instruction else ""

        if is_final:
            return f"""{prefix}你是游戏裁判。所有轮次已经结束，请根据以下信息做出终局裁决。

游戏规则：{effective_rules}
原始任务：{input_text}
当前共享状态：
{shared_state_str}
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
当前共享状态：{shared_state_str}
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
                                            participants, round_num, turn_strategy, task):
        """Execute one round with simultaneous strategy"""
        tasks = []
        for agent, indexed_role, idx in participants:
            prompt = self._build_participant_prompt(
                collab, input_text, shared_state, indexed_role, idx, round_num, turn_strategy)
            t = A2ATask(id=str(uuid.uuid4()), input=prompt)
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
                                          round_num, turn_strategy, task):
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
                turn_strategy, round_actions_so_far)
            agent_task = A2ATask(id=str(uuid.uuid4()), input=prompt)
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
        if ruling["updated_state"]:
            # Caller is responsible for updating shared_state
            pass

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
                        round_num, turn_strategy, task)
                else:
                    round_actions = await self._execute_round_sequential(
                        collab, input_text, shared_state, participants,
                        participant_order, order_map, round_num, turn_strategy, task)

                all_round_actions.append((round_num, round_actions))

                # Store actions in shared state
                for action_line in round_actions:
                    role_part = action_line.split(":")[0].strip()
                    shared_state[f"round_{round_num}_{role_part}_output"] = action_line

                # Referee per round
                if referee_enabled and referee_agent and referee_timing == "per_round":
                    referee_prompt = self._build_referee_prompt(
                        collab, input_text, shared_state,
                        "\n".join(round_actions), game_rules)
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
                        all_actions_text, game_rules, is_final=True)
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
        await self._create_task_record(collab.id, task)

        try:
            yield {
                "type": "task_start",
                "task_id": task.id,
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

            if turn_strategy == "sequential":
                order_map, participant_order = self._build_order_map(
                    participants, participant_order, config)

            yield {
                "type": "game_start",
                "shared_state": shared_state,
                "participants": [p[1] for p in participants],
                "turn_strategy": turn_strategy,
                "referee_enabled": referee_enabled
            }

            task.add_message(A2AMessageRole.USER, f"Game start: {input_text}")

            all_round_actions = []

            for round_num in range(1, max_rounds + 1):
                yield {"type": "round_start", "round": round_num, "max_rounds": max_rounds}

                round_actions = []

                if turn_strategy == "simultaneous":
                    tasks = []
                    for agent, indexed_role, idx in participants:
                        prompt = self._build_participant_prompt(
                            collab, input_text, shared_state, indexed_role, idx, round_num, turn_strategy)
                        t = A2ATask(id=str(uuid.uuid4()), input=prompt)
                        tasks.append((agent, indexed_role, idx, t))

                    for agent, indexed_role, idx, _ in tasks:
                        yield {
                            "type": "agent_start",
                            "agent_id": agent.agent_id,
                            "role": indexed_role,
                            "round": round_num
                        }

                    results = await asyncio.gather(
                        *[agent_registry.call_agent(a.agent_id, t) for a, _, _, t in tasks],
                        return_exceptions=True
                    )

                    for i, result in enumerate(results):
                        agent, indexed_role, idx, _ = tasks[i]
                        if isinstance(result, Exception):
                            action = f"[{indexed_role} failed: {str(result)}]"
                        else:
                            action = result.output or ""
                        round_actions.append(f"{indexed_role}: {action}")

                        yield {
                            "type": "agent_message",
                            "agent_id": agent.agent_id,
                            "role": indexed_role,
                            "content": action,
                            "round": round_num
                        }
                        yield {"type": "agent_done", "agent_id": agent.agent_id, "round": round_num}

                else:  # sequential
                    round_actions_so_far = []
                    for role_key in participant_order:
                        agent = order_map.get(role_key)
                        if not agent:
                            yield {"type": "task_failed", "error": f"No agent found for role: {role_key}"}
                            return

                        idx = next((i for a, r, i in participants if r == role_key or a.role == role_key), 0)

                        prompt = self._build_participant_prompt(
                            collab, input_text, shared_state, role_key, idx, round_num,
                            turn_strategy, round_actions_so_far)

                        yield {
                            "type": "agent_start",
                            "agent_id": agent.agent_id,
                            "role": role_key,
                            "round": round_num
                        }

                        agent_task = A2ATask(id=str(uuid.uuid4()), input=prompt)
                        result = await agent_registry.call_agent(agent.agent_id, agent_task)
                        action = result.output or ""
                        action_line = f"{role_key}: {action}"
                        round_actions.append(action_line)
                        round_actions_so_far.append(action_line)

                        yield {
                            "type": "agent_message",
                            "agent_id": agent.agent_id,
                            "role": role_key,
                            "content": action,
                            "round": round_num
                        }
                        yield {"type": "agent_done", "agent_id": agent.agent_id, "round": round_num}

                    shared_state[f"round_{round_num}_actions"] = round_actions_so_far

                all_round_actions.append((round_num, round_actions))

                # Store actions in shared state
                for action_line in round_actions:
                    role_part = action_line.split(":")[0].strip()
                    content_part = ":".join(action_line.split(":")[1:]).strip()
                    shared_state[f"round_{round_num}_{role_part}_output"] = content_part

                # Referee per round
                if referee_enabled and referee_agent and referee_timing == "per_round":
                    yield {
                        "type": "agent_start",
                        "agent_id": referee_agent.agent_id,
                        "role": "referee",
                        "round": round_num
                    }

                    referee_prompt = self._build_referee_prompt(
                        collab, input_text, shared_state,
                        "\n".join(round_actions), game_rules)
                    referee_task = A2ATask(id=str(uuid.uuid4()), input=referee_prompt)
                    referee_result = await agent_registry.call_agent(referee_agent.agent_id, referee_task)

                    ruling = self._parse_referee_output(referee_result.output or "")

                    yield {
                        "type": "agent_message",
                        "agent_id": referee_agent.agent_id,
                        "role": "referee",
                        "content": ruling["round_result"],
                        "round": round_num,
                        "ruling": ruling
                    }
                    yield {"type": "agent_done", "agent_id": referee_agent.agent_id, "round": round_num}

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
                # All rounds completed
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
                        all_actions_text, game_rules, is_final=True)
                    referee_task = A2ATask(id=str(uuid.uuid4()), input=referee_prompt)
                    referee_result = await agent_registry.call_agent(referee_agent.agent_id, referee_task)

                    ruling = self._parse_referee_output(referee_result.output or "")

                    yield {
                        "type": "agent_message",
                        "agent_id": referee_agent.agent_id,
                        "role": "referee",
                        "content": ruling["round_result"],
                        "round": max_rounds,
                        "ruling": ruling
                    }
                    yield {"type": "agent_done", "agent_id": referee_agent.agent_id, "round": max_rounds}

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
            await self._update_task_record(task, completed=True)
            yield {"type": "task_failed", "task_id": task.id, "error": str(e)}
