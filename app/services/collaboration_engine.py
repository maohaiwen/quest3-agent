"""Collaboration Engine - executes multi-agent collaboration patterns"""
import asyncio
import logging
import uuid
import json
from typing import List, Optional, Dict, Any
from datetime import datetime

from app.models.a2a import A2ATask, A2ATaskStatus, A2ATaskStatusState, A2AMessage, A2AMessageRole, A2APart
from app.models.collaboration import CollaborationMode, CollaborationResponse
from app.services.collaboration_service import collaboration_service
from app.services.agent_registry import agent_registry
from app.database.connection import DatabaseConnection
from app.config import settings

logger = logging.getLogger(__name__)


class BaseCollaborationMode:
    """Base class for collaboration modes"""

    async def execute(self, collab: CollaborationResponse, input_text: str) -> A2ATask:
        """Execute collaboration mode"""
        raise NotImplementedError

    async def execute_stream(self, collab: CollaborationResponse, input_text: str):
        """Execute collaboration mode with SSE events streaming.
        Yields dicts: {"type": "...", ...}
        """
        # Default: run execute and yield a complete event
        task = await self.execute(collab, input_text)
        yield {
            "type": "task_complete",
            "task_id": task.id,
            "status": task.status.state.value,
            "output": task.output,
            "messages": [m.dict() for m in task.messages]
        }


class SupervisorCollaboration(BaseCollaborationMode):
    """Supervisor mode: one supervisor agent splits task, child agents execute in parallel, then summarize"""

    async def execute(self, collab: CollaborationResponse, input_text: str) -> A2ATask:
        task = A2ATask(
            id=str(uuid.uuid4()),
            input=input_text,
            status=A2ATaskStatus(state=A2ATaskStatusState.RUNNING)
        )

        # Create task record in DB
        await self._create_task_record(collab.id, task)

        try:
            # Get supervisor and children
            supervisor_agent = next((a for a in collab.agents if a.role == "supervisor"), None)
            child_agents = [a for a in collab.agents if a.role == "child"]

            if not supervisor_agent:
                raise ValueError("No supervisor agent found in collaboration")
            if not child_agents:
                raise ValueError("No child agents found in collaboration")

            # Step 1: Supervisor splits the task
            # Build child agent info with names for LLM readability
            child_agent_info = []
            for a in child_agents:
                agent_card = agent_registry.get_agent_card(a.agent_id)
                agent_name = agent_card.name if agent_card else a.agent_id
                child_agent_info.append({"agent_id": a.agent_id, "name": agent_name, "config": a})

            agent_list_str = chr(10).join(
                f"- [{i+1}] {info['name']} (ID: {info['agent_id']})"
                for i, info in enumerate(child_agent_info)
            )

            split_prompt = collab.config_json.get("split_prompt")
            if not split_prompt:
                split_prompt = f"""请将以下任务拆分成多个子任务，分配给以下子Agent：
任务：{input_text}
子Agent列表：
{agent_list_str}
请按以下格式输出每个子任务（每行一个，使用Agent编号或名称）：
[1] 具体任务描述
[2] 具体任务描述
或：
子任务1：分配给 [Agent名称或编号] - 具体任务描述
子任务2：分配给 [Agent名称或编号] - 具体任务描述"""
            else:
                # Append agent list info to custom split_prompt so LLM knows the agents
                split_prompt = f"""{split_prompt}

当前任务：{input_text}
可分配的子Agent列表：
{agent_list_str}
请按以上格式输出每个子任务，使用Agent编号或名称来分配。"""

            split_task = A2ATask(id=str(uuid.uuid4()), input=split_prompt)
            split_result = await agent_registry.call_agent(supervisor_agent.agent_id, split_task)

            # Parse split result to get sub-tasks (simple parsing)
            sub_tasks = self._parse_subtasks(split_result.output, child_agent_info)

            # Step 2: Execute child agents in parallel or sequence
            parallel = collab.config_json.get("parallel_execution", True)

            if parallel:
                # Parallel execution
                tasks = []
                for child_agent, sub_input in sub_tasks:
                    enhanced_input = self._enhance_child_task(sub_input, input_text)
                    t = A2ATask(id=str(uuid.uuid4()), input=enhanced_input)
                    tasks.append(agent_registry.call_agent(child_agent.agent_id, t))

                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Collect results
                child_results = []
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.error(f"Child agent {sub_tasks[i][0].agent_id} failed: {result}")
                        child_results.append(f"[Agent {sub_tasks[i][0].agent_id} failed: {str(result)}]")
                    else:
                        child_results.append(result.output or "")
                        # Update task record
                        await self._update_task_record(result)
            else:
                # Sequential execution
                child_results = []
                for child_agent, sub_input in sub_tasks:
                    enhanced_input = self._enhance_child_task(sub_input, input_text)
                    t = A2ATask(id=str(uuid.uuid4()), input=enhanced_input)
                    try:
                        result = await agent_registry.call_agent(child_agent.agent_id, t)
                        child_results.append(result.output or "")
                        await self._update_task_record(result)
                    except Exception as e:
                        logger.error(f"Child agent {child_agent.agent_id} failed: {e}")
                        child_results.append(f"[Agent {child_agent.agent_id} failed: {str(e)}]")

            # Step 3: Supervisor summarizes results
            # Build child result parts (always needed for summary)
            result_parts = []
            for i in range(len(child_results)):
                agent_card = agent_registry.get_agent_card(sub_tasks[i][0].agent_id)
                agent_name = agent_card.name if agent_card else sub_tasks[i][0].agent_id
                result_parts.append(f"Agent {agent_name}: {child_results[i]}")
            child_results_str = chr(10).join(result_parts)

            summary_prompt = collab.config_json.get("summary_prompt")
            if not summary_prompt:
                summary_prompt = f"""以下是各子Agent的执行结果，请汇总为最终答案：
原始任务：{input_text}
子任务结果：
{child_results_str}
请输出最终的汇总结果："""
            else:
                # Append child results to custom summary_prompt
                summary_prompt = f"""{summary_prompt}

【重要】你必须基于以下子任务执行结果来汇总，不要忽略这些内容：

原始任务：{input_text}

各子Agent的执行结果如下：
{child_results_str}

请基于以上子任务结果进行整合汇总，直接输出最终内容，不要要求更多信息。"""

            summary_task = A2ATask(id=str(uuid.uuid4()), input=summary_prompt)
            summary_result = await agent_registry.call_agent(supervisor_agent.agent_id, summary_task)

            # Update main task
            task.set_completed(summary_result.output or "No summary generated")
            task.add_message(A2AMessageRole.AGENT, summary_result.output or "")

            # Update task record in DB
            await self._update_task_record(task, completed=True)

            # Increment usage count
            await collaboration_service.increment_usage(collab.id)

            return task

        except Exception as e:
            logger.error(f"Supervisor collaboration failed: {e}", exc_info=True)
            task.set_failed(str(e))
            await self._update_task_record(task, completed=True)
            return task

    async def execute_stream(self, collab: CollaborationResponse, input_text: str):
        """Execute supervisor mode with SSE event streaming"""
        import json

        task = A2ATask(
            id=str(uuid.uuid4()),
            input=input_text,
            status=A2ATaskStatus(state=A2ATaskStatusState.RUNNING)
        )

        await self._create_task_record(collab.id, task)

        try:
            yield {
                "type": "task_start",
                "task_id": task.id,
                "input": input_text,
                "mode": "supervisor"
            }

            supervisor_agent = next((a for a in collab.agents if a.role == "supervisor"), None)
            child_agents = [a for a in collab.agents if a.role == "child"]

            if not supervisor_agent or not child_agents:
                yield {
                    "type": "task_failed",
                    "error": "Missing supervisor or child agents"
                }
                return

            # Step 1: Supervisor splits task
            yield {
                "type": "agent_start",
                "agent_id": supervisor_agent.agent_id,
                "role": "supervisor",
                "round": 0
            }

            split_prompt = collab.config_json.get("split_prompt")
            # Build child agent info with names (always needed for parsing)
            child_agent_info = []
            for a in child_agents:
                agent_card = agent_registry.get_agent_card(a.agent_id)
                agent_name = agent_card.name if agent_card else a.agent_id
                child_agent_info.append({"agent_id": a.agent_id, "name": agent_name, "config": a})

            agent_list_str = chr(10).join(
                f"- [{i+1}] {info['name']} (ID: {info['agent_id']})"
                for i, info in enumerate(child_agent_info)
            )

            if not split_prompt:
                split_prompt = f"""请将以下任务拆分成多个子任务，分配给以下子Agent：
任务：{input_text}
子Agent列表：
{agent_list_str}
请按以下格式输出每个子任务（每行一个，使用Agent编号或名称）：
[1] 具体任务描述
[2] 具体任务描述
或：
子任务1：分配给 [Agent名称或编号] - 具体任务描述
子任务2：分配给 [Agent名称或编号] - 具体任务描述"""
            else:
                # Append agent list info to custom split_prompt so LLM knows the agents
                split_prompt = f"""{split_prompt}

当前任务：{input_text}
可分配的子Agent列表：
{agent_list_str}
请按以上格式输出每个子任务，使用Agent编号或名称来分配。"""

            split_task = A2ATask(id=str(uuid.uuid4()), input=split_prompt)
            split_result = await agent_registry.call_agent(supervisor_agent.agent_id, split_task)

            yield {
                "type": "agent_message",
                "agent_id": supervisor_agent.agent_id,
                "role": "supervisor",
                "content": split_result.output or "",
                "round": 0
            }

            yield {"type": "agent_done", "agent_id": supervisor_agent.agent_id, "round": 0}

            # Parse sub-tasks
            sub_tasks = self._parse_subtasks(split_result.output, child_agent_info)

            # Step 2: Execute child agents (parallel or sequential)
            parallel = collab.config_json.get("parallel_execution", True)
            logger.info(f"Supervisor: parsed {len(sub_tasks)} sub-tasks from split output (parallel={parallel})")
            child_results = []

            if parallel and len(sub_tasks) > 1:
                # Parallel execution: emit all agent_start, then gather, then emit results
                for idx, (child_agent, sub_input) in enumerate(sub_tasks):
                    yield {
                        "type": "agent_start",
                        "agent_id": child_agent.agent_id,
                        "role": "child",
                        "round": idx + 1
                    }

                tasks = []
                for child_agent, sub_input in sub_tasks:
                    enhanced_input = self._enhance_child_task(sub_input, input_text)
                    t = A2ATask(id=str(uuid.uuid4()), input=enhanced_input)
                    tasks.append(agent_registry.call_agent(child_agent.agent_id, t))

                results = await asyncio.gather(*tasks, return_exceptions=True)

                for idx, result in enumerate(results):
                    child_agent = sub_tasks[idx][0]
                    if isinstance(result, Exception):
                        child_results.append(f"[Agent {child_agent.agent_id} failed: {str(result)}]")
                    else:
                        child_results.append(result.output or "")
                        await self._update_task_record(result)

                    yield {
                        "type": "agent_message",
                        "agent_id": child_agent.agent_id,
                        "role": "child",
                        "content": child_results[-1],
                        "round": idx + 1
                    }
                    yield {"type": "agent_done", "agent_id": child_agent.agent_id, "round": idx + 1}
            else:
                # Sequential execution
                for idx, (child_agent, sub_input) in enumerate(sub_tasks):
                    yield {
                        "type": "agent_start",
                        "agent_id": child_agent.agent_id,
                        "role": "child",
                        "round": idx + 1
                    }

                    enhanced_input = self._enhance_child_task(sub_input, input_text)
                    t = A2ATask(id=str(uuid.uuid4()), input=enhanced_input)
                    result = await agent_registry.call_agent(child_agent.agent_id, t)
                    child_results.append(result.output or "")

                    yield {
                        "type": "agent_message",
                        "agent_id": child_agent.agent_id,
                        "role": "child",
                        "content": result.output or "",
                        "round": idx + 1
                    }

                    yield {"type": "agent_done", "agent_id": child_agent.agent_id, "round": idx + 1}

                    await self._update_task_record(result)

            # Step 3: Supervisor summarizes
            yield {
                "type": "agent_start",
                "agent_id": supervisor_agent.agent_id,
                "role": "supervisor",
                "round": 999  # Summary round
            }

            # Build child result parts (always needed for summary)
            result_parts = []
            for i in range(len(child_results)):
                agent_card = agent_registry.get_agent_card(sub_tasks[i][0].agent_id)
                agent_name = agent_card.name if agent_card else sub_tasks[i][0].agent_id
                result_parts.append(f"Agent {agent_name}: {child_results[i]}")
            child_results_str = chr(10).join(result_parts)

            summary_prompt = collab.config_json.get("summary_prompt")
            if not summary_prompt:
                summary_prompt = f"""以下是各子Agent的执行结果，请汇总为最终答案：
原始任务：{input_text}
子任务结果：
{child_results_str}
请输出最终的汇总结果："""
            else:
                # Append child results to custom summary_prompt
                summary_prompt = f"""{summary_prompt}

【重要】你必须基于以下子任务执行结果来汇总，不要忽略这些内容：

原始任务：{input_text}

各子Agent的执行结果如下：
{child_results_str}

请基于以上子任务结果进行整合汇总，直接输出最终内容，不要要求更多信息。"""

            summary_task = A2ATask(id=str(uuid.uuid4()), input=summary_prompt)
            summary_result = await agent_registry.call_agent(supervisor_agent.agent_id, summary_task)

            task.set_completed(summary_result.output or "No summary generated")
            task.add_message(A2AMessageRole.AGENT, summary_result.output or "")

            yield {
                "type": "agent_message",
                "agent_id": supervisor_agent.agent_id,
                "role": "supervisor",
                "content": summary_result.output or "",
                "round": 999
            }

            yield {"type": "agent_done", "agent_id": supervisor_agent.agent_id, "round": 999}

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
            logger.error(f"Supervisor collaboration failed: {e}", exc_info=True)
            task.set_failed(str(e))
            await self._update_task_record(task, completed=True)
            yield {
                "type": "task_failed",
                "task_id": task.id,
                "error": str(e)
            }

    def _parse_subtasks(self, split_output: str, child_agent_info: list) -> list:
        """Parse supervisor's split output to get sub-tasks for each child agent.

        child_agent_info: list of {"agent_id": ..., "name": ..., "config": CollaborationAgentConfig}
        Supports matching by: [N] notation, N. numbered list, agent name, agent ID.
        Note: same agent_id can appear multiple times (e.g. 3 child slots all using same agent).
        We use positional index to handle duplicate agent_ids correctly.
        """
        import re
        sub_tasks = []
        lines = split_output.split('\n')

        # Track which child slots have been assigned (by position index)
        assigned_indices = set()

        # Strategy 1: Try to match numbered items that correspond to child agent indices
        # Supports formats: [1], 1., Agent 1, 子任务1, #1, （1）
        numbered_pattern = re.compile(
            r'(?:^|\n)\s*(?:\[|\(|#|第?|Agent\s*)(\d+)(?:\]|\)|\.|[：:.)）]|\s)'
        )
        # Find all numbered items and their task descriptions
        numbered_items = []
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue

            # Match various numbered formats
            m = re.match(r'^\s*(?:\[|\(|#)?\s*(\d+)\s*(?:\]|\)|\.|[：:.)）])\s*(.*)', line_stripped)
            if not m:
                # Also match "Agent N" or "子任务N" at start
                m = re.match(r'^\s*(?:Agent\s*(\d+)|子任务\s*(\d+))[：:.)\]）]?\s*(.*)', line_stripped)
                if m:
                    idx_str = m.group(1) or m.group(2)
                    m = type('M', (), {'group': lambda self, i: idx_str if i == 1 else line_stripped})()

            if m:
                idx_str = m.group(1)
                task_desc = line_stripped  # Keep full line as desc initially
                try:
                    idx = int(idx_str)
                    if 1 <= idx <= len(child_agent_info):
                        # Extract task description: everything after the number marker
                        # Remove the number prefix from the line
                        remaining = re.sub(
                            r'^\s*(?:\[|\(|#)?\s*\d+\s*(?:\]|\)|\.|[：:.)）])\s*',
                            '', line_stripped
                        )
                        remaining = re.sub(
                            r'^\s*(?:Agent\s*\d+|子任务\s*\d+)[：:.)\]）]?\s*',
                            '', line_stripped
                        )
                        if remaining and len(remaining) > 5:
                            task_desc = remaining
                        numbered_items.append((idx - 1, task_desc, line_stripped))
                except ValueError:
                    pass

        # Assign numbered items to child slots by position
        for slot_idx, task_desc, full_line in numbered_items:
            if slot_idx not in assigned_indices and slot_idx < len(child_agent_info):
                assigned_indices.add(slot_idx)
                info = child_agent_info[slot_idx]
                # Clean up task description
                task_desc = self._clean_task_desc(task_desc)
                sub_tasks.append((info["config"], task_desc))

        # Strategy 2: If not enough items found, try matching by agent name with positional round-robin
        if len(sub_tasks) < len(child_agent_info):
            agent_name_usage = {}  # name -> next slot index to assign
            for line in lines:
                line_stripped = line.strip()
                if not line_stripped:
                    continue

                for info in child_agent_info:
                    name = info["name"]
                    if name in line_stripped:
                        # Get next unassigned slot index for this name
                        start_idx = agent_name_usage.get(name, 0)
                        found_slot = None
                        for i in range(start_idx, len(child_agent_info)):
                            if i not in assigned_indices and child_agent_info[i]["agent_id"] == info["agent_id"]:
                                found_slot = i
                                break
                        if found_slot is not None:
                            assigned_indices.add(found_slot)
                            agent_name_usage[name] = found_slot + 1
                            parts = line_stripped.split(name, 1)
                            task_desc = parts[1].strip().lstrip('-—–:：').strip() if len(parts) > 1 else line_stripped
                            task_desc = self._clean_task_desc(task_desc)
                            sub_tasks.append((info["config"], task_desc))
                        break

        # Strategy 3: If still not enough, distribute the original task to remaining slots
        if len(sub_tasks) < len(child_agent_info):
            for i, info in enumerate(child_agent_info):
                if i not in assigned_indices:
                    sub_tasks.append((info["config"], f"请协助完成以下任务：\n{split_output}"))

        # Sort by child agent position order
        sub_tasks.sort(key=lambda x: next(
            (i for i, info in enumerate(child_agent_info) if info["config"] == x[0]),
            999
        ))

        return sub_tasks

    @staticmethod
    def _clean_task_desc(task_desc: str) -> str:
        """Clean up a task description string"""
        import re
        # Remove markdown bold markers
        task_desc = re.sub(r'\*\*', '', task_desc)
        # Remove leading "子任务N：" prefix
        task_desc = re.sub(r'^子任务\d+[：:]\s*', '', task_desc)
        # Remove leading "Agent N" prefix if present
        task_desc = re.sub(r'^Agent\s*\d+\s*[：:.)\)）]?\s*', '', task_desc)
        # Remove agent ID references like "(047b856a...)"
        task_desc = re.sub(r'\([0-9a-f]{8,}\.\.\.\)\s*', '', task_desc)
        task_desc = task_desc.strip()
        return task_desc

    def _enhance_child_task(self, sub_input: str, original_task: str) -> str:
        """Enhance child agent task input with collaboration context.

        Ensures child agents know they must use tools to get real data
        instead of just outputting an analysis framework.
        """
        return f"""【协作子任务】{sub_input}

原始任务：{original_task}

重要要求：
1. 你必须使用可用的工具（如web_search搜索资讯、代码解释器获取和分析数据）获取实际数据后再进行分析
2. 不要只输出分析框架或大纲，必须包含具体的数据、数值和分析结论
3. 如果工具调用失败，请尝试不同的搜索关键词或数据获取方式
4. 分析结果必须基于实际获取到的数据，不能凭空编造"""

    async def _create_task_record(self, collab_id: str, task: A2ATask):
        """Create task record in database"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()
        try:
            now = datetime.utcnow().isoformat()
            await db.execute("""
            INSERT INTO collaboration_tasks
            (id, collaboration_id, task_id, input, output, status, messages_json, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                collab_id,
                task.id,
                task.input,
                task.output,
                task.status.state.value,
                json.dumps([m.dict() for m in task.messages]),
                now,
                None
            ))
            await db.commit()
        finally:
            await db.disconnect()

    async def _update_task_record(self, task: A2ATask, completed: bool = False):
        """Update task record in database"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()
        try:
            completed_at = datetime.utcnow().isoformat() if completed else None
            await db.execute("""
            UPDATE collaboration_tasks
            SET output = ?, status = ?, messages_json = ?, completed_at = ?
            WHERE task_id = ?
            """, (
                task.output,
                task.status.state.value,
                json.dumps([m.dict() for m in task.messages]),
                completed_at,
                task.id
            ))
            await db.commit()
        finally:
            db.disconnect()


class GenerateDiscriminateCollaboration(BaseCollaborationMode):
    """Adversarial mode: generator produces content, discriminator validates, loop until pass or max rounds"""

    async def execute(self, collab: CollaborationResponse, input_text: str) -> A2ATask:
        task = A2ATask(
            id=str(uuid.uuid4()),
            input=input_text,
            status=A2ATaskStatus(state=A2ATaskStatusState.RUNNING)
        )

        await self._create_task_record(collab.id, task)

        try:
            # Get agents
            generator_agent = next((a for a in collab.agents if a.role == "generator"), None)
            discriminator_agent = next((a for a in collab.agents if a.role == "discriminator"), None)
            judge_agent = next((a for a in collab.agents if a.role == "judge"), None)

            if not generator_agent:
                raise ValueError("No generator agent found")
            if not discriminator_agent:
                raise ValueError("No discriminator agent found")

            max_rounds = collab.config_json.get("max_rounds", 3)
            termination_on_pass = collab.config_json.get("termination_on_pass", True)

            current_input = input_text
            task.add_message(A2AMessageRole.USER, f"Initial input: {input_text}")

            for round_num in range(1, max_rounds + 1):
                logger.info(f"Adversarial round {round_num}/{max_rounds}")

                # Step 1: Generator produces content
                gen_task = A2ATask(id=str(uuid.uuid4()), input=current_input)
                gen_result = await agent_registry.call_agent(generator_agent.agent_id, gen_task)

                task.add_message(
                    A2AMessageRole.AGENT,
                    f"[Round {round_num}] Generator output: {gen_result.output}"
                )

                # Step 2: Discriminator validates
                dis_input = f"请校验以下内容是否合格：\n{gen_result.output}\n请回答：通过 或 不通过（并说明原因）"
                dis_task = A2ATask(id=str(uuid.uuid4()), input=dis_input)
                dis_result = await agent_registry.call_agent(discriminator_agent.agent_id, dis_task)

                task.add_message(
                    A2AMessageRole.AGENT,
                    f"[Round {round_num}] Discriminator output: {dis_result.output}"
                )

                # Step 3: Check termination
                if termination_on_pass and self._is_pass(dis_result.output):
                    task.set_completed(gen_result.output)
                    task.add_message(A2AMessageRole.AGENT, f"通过校验，共 {round_num} 轮")
                    break

                # Step 4: Prepare input for next round
                if round_num < max_rounds:
                    current_input = f"原始任务：{input_text}\n上轮生成内容：{gen_result.output}\n校验反馈：{dis_result.output}\n请优化并重新生成"

            else:
                # Max rounds reached
                task.set_failed(f"达到最大轮次 {max_rounds}，未通过校验")
                task.add_message(A2AMessageRole.AGENT, f"达到最大轮次 {max_rounds}，未通过校验")

            # If judge is enabled, get final judgment
            if judge_agent and task.status.state == A2ATaskStatusState.COMPLETED:
                judge_input = f"请对以下内容做出最终评判：\n{task.output}"
                judge_task = A2ATask(id=str(uuid.uuid4()), input=judge_input)
                judge_result = await agent_registry.call_agent(judge_agent.agent_id, judge_task)
                task.add_message(A2AMessageRole.AGENT, f"裁判最终评判：{judge_result.output}")

            await self._update_task_record(task, completed=True)
            await collaboration_service.increment_usage(collab.id)

            return task

        except Exception as e:
            logger.error(f"Adversarial collaboration failed: {e}", exc_info=True)
            task.set_failed(str(e))
            await self._update_task_record(task, completed=True)
            return task

    async def execute_stream(self, collab: CollaborationResponse, input_text: str):
        """Execute adversarial mode with SSE event streaming"""
        import json

        task = A2ATask(
            id=str(uuid.uuid4()),
            input=input_text,
            status=A2ATaskStatus(state=A2ATaskStatusState.RUNNING)
        )

        await self._create_task_record(collab.id, task)

        try:
            yield {
                "type": "task_start",
                "task_id": task.id,
                "input": input_text,
                "mode": "adversarial"
            }

            # Get agents
            generator_agent = next((a for a in collab.agents if a.role == "generator"), None)
            discriminator_agent = next((a for a in collab.agents if a.role == "discriminator"), None)
            judge_agent = next((a for a in collab.agents if a.role == "judge"), None)

            if not generator_agent or not discriminator_agent:
                yield {
                    "type": "task_failed",
                    "error": "Missing generator or discriminator agent"
                }
                return

            max_rounds = collab.config_json.get("max_rounds", 3)
            termination_on_pass = collab.config_json.get("termination_on_pass", True)

            current_input = input_text
            task.add_message(A2AMessageRole.USER, f"Initial input: {input_text}")

            for round_num in range(1, max_rounds + 1):
                yield {
                    "type": "round_start",
                    "round": round_num,
                    "max_rounds": max_rounds
                }

                # Step 1: Generator produces content
                yield {
                    "type": "agent_start",
                    "agent_id": generator_agent.agent_id,
                    "role": "generator",
                    "round": round_num
                }

                gen_task = A2ATask(id=str(uuid.uuid4()), input=current_input)
                gen_result = await agent_registry.call_agent(generator_agent.agent_id, gen_task)

                task.add_message(
                    A2AMessageRole.AGENT,
                    f"[Round {round_num}] Generator output: {gen_result.output}"
                )

                yield {
                    "type": "agent_message",
                    "agent_id": generator_agent.agent_id,
                    "role": "generator",
                    "content": gen_result.output or "",
                    "round": round_num
                }

                yield {"type": "agent_done", "agent_id": generator_agent.agent_id, "round": round_num}

                # Step 2: Discriminator validates
                yield {
                    "type": "agent_start",
                    "agent_id": discriminator_agent.agent_id,
                    "role": "discriminator",
                    "round": round_num
                }

                dis_input = f"请校验以下内容是否合格：\n{gen_result.output}\n请回答：通过 或 不通过（并说明原因）"
                dis_task = A2ATask(id=str(uuid.uuid4()), input=dis_input)
                dis_result = await agent_registry.call_agent(discriminator_agent.agent_id, dis_task)

                task.add_message(
                    A2AMessageRole.AGENT,
                    f"[Round {round_num}] Discriminator output: {dis_result.output}"
                )

                yield {
                    "type": "agent_message",
                    "agent_id": discriminator_agent.agent_id,
                    "role": "discriminator",
                    "content": dis_result.output or "",
                    "round": round_num
                }

                yield {"type": "agent_done", "agent_id": discriminator_agent.agent_id, "round": round_num}

                # Step 3: Check termination
                passed = self._is_pass(dis_result.output)

                yield {
                    "type": "round_end",
                    "round": round_num,
                    "passed": passed
                }

                if termination_on_pass and passed:
                    task.set_completed(gen_result.output)
                    task.add_message(A2AMessageRole.AGENT, f"通过校验，共 {round_num} 轮")
                    break

                # Step 4: Prepare input for next round
                if round_num < max_rounds:
                    current_input = f"原始任务：{input_text}\n上轮生成内容：{gen_result.output}\n校验反馈：{dis_result.output}\n请优化并重新生成"

            else:
                # Max rounds reached
                task.set_failed(f"达到最大轮次 {max_rounds}，未通过校验")
                task.add_message(A2AMessageRole.AGENT, f"达到最大轮次 {max_rounds}，未通过校验")

            # If judge is enabled, get final judgment
            if judge_agent and task.status.state == A2ATaskStatusState.COMPLETED:
                yield {
                    "type": "agent_start",
                    "agent_id": judge_agent.agent_id,
                    "role": "judge",
                    "round": 999
                }

                judge_input = f"请对以下内容做出最终评判：\n{task.output}"
                judge_task = A2ATask(id=str(uuid.uuid4()), input=judge_input)
                judge_result = await agent_registry.call_agent(judge_agent.agent_id, judge_task)
                task.add_message(A2AMessageRole.AGENT, f"裁判最终评判：{judge_result.output}")

                yield {
                    "type": "agent_message",
                    "agent_id": judge_agent.agent_id,
                    "role": "judge",
                    "content": judge_result.output or "",
                    "round": 999
                }

                yield {"type": "agent_done", "agent_id": judge_agent.agent_id, "round": 999}

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
            logger.error(f"Adversarial collaboration failed: {e}", exc_info=True)
            task.set_failed(str(e))
            await self._update_task_record(task, completed=True)
            yield {
                "type": "task_failed",
                "task_id": task.id,
                "error": str(e)
            }

    def _is_pass(self, discriminator_output: str) -> bool:
        """Check if discriminator output indicates pass"""
        pass_keywords = ["通过", "pass", "合格", "acceptable", "good", "ok"]
        fail_keywords = ["不通过", "fail", "不合格", "不可接受", "bad"]

        output_lower = discriminator_output.lower()

        # If any pass keyword found and no fail keyword, consider it pass
        has_pass = any(kw in output_lower for kw in pass_keywords)
        has_fail = any(kw in output_lower for kw in fail_keywords)

        return has_pass and not has_fail

    async def _create_task_record(self, collab_id: str, task: A2ATask):
        """Create task record in database"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()
        try:
            now = datetime.utcnow().isoformat()
            await db.execute("""
            INSERT INTO collaboration_tasks
            (id, collaboration_id, task_id, input, output, status, messages_json, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                collab_id,
                task.id,
                task.input,
                task.output,
                task.status.state.value,
                json.dumps([m.dict() for m in task.messages]),
                now,
                None
            ))
            await db.commit()
        finally:
            await db.disconnect()

    async def _update_task_record(self, task: A2ATask, completed: bool = False):
        """Update task record in database"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()
        try:
            completed_at = datetime.utcnow().isoformat() if completed else None
            await db.execute("""
            UPDATE collaboration_tasks
            SET output = ?, status = ?, messages_json = ?, completed_at = ?
            WHERE task_id = ?
            """, (
                task.output,
                task.status.state.value,
                json.dumps([m.dict() for m in task.messages]),
                completed_at,
                task.id
            ))
            await db.commit()
        finally:
            await db.disconnect()


class GameCollaboration(BaseCollaborationMode):
    """Game mode: supports simultaneous and turn-based strategies with referee judgment.

    Turn strategies:
    - simultaneous: all participants act at once (e.g. rock-paper-scissors, auctions)
    - turn_based: participants take turns (e.g. chess, poker)

    A referee agent judges rounds, updates shared state, and determines the winner.
    """

    # Default referee prompt template
    DEFAULT_REFEREE_PROMPT = """你是游戏裁判。请根据以下信息裁决本轮结果。

游戏规则：{game_rules}
原始任务：{input}
当前共享状态：{shared_state}
本轮各参与者的行动：
{round_actions}

请以JSON格式输出裁决结果，格式如下：
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

    DEFAULT_PARTICIPANT_PROMPT = """你正在参与一个博弈游戏。

游戏规则：{game_rules}
原始任务：{input}
当前共享状态：{shared_state}
你是：{role}（第{player_index}位参与者）
当前轮次：第{round}轮

请根据游戏规则和当前状态，做出你的选择。只输出你的行动，不要输出其他内容。"""

    DEFAULT_TURN_BASED_PARTICIPANT_PROMPT = """你正在参与一个轮流行动的博弈游戏。

游戏规则：{game_rules}
原始任务：{input}
当前共享状态：{shared_state}
你是：{role}（第{player_index}位参与者）
当前轮次：第{round}轮
轮到你行动了。

请根据游戏规则和当前状态，做出你的选择。只输出你的行动，不要输出其他内容。"""

    def _get_participants(self, collab: CollaborationResponse) -> list:
        """Get participant agents with their indexed roles"""
        participants = []
        idx = 0
        for agent in collab.agents:
            if agent.role in ("participant", "player_black", "player_white"):
                # Assign indexed role for identification
                indexed_role = f"participant_{idx}" if agent.role == "participant" else agent.role
                participants.append((agent, indexed_role, idx))
                idx += 1
        return participants

    def _get_referee(self, collab: CollaborationResponse):
        """Get referee agent if configured"""
        return next((a for a in collab.agents if a.role == "referee"), None)

    def _build_participant_prompt(self, collab: CollaborationResponse, input_text: str,
                                   shared_state: dict, role: str, player_index: int,
                                   round_num: int, turn_strategy: str) -> str:
        """Build prompt for a participant agent"""
        config = collab.config_json
        game_rules = config.get("game_rules", "")
        custom_template = config.get("round_input_template")

        if custom_template:
            # Legacy support: use custom template if provided
            return custom_template.format(
                shared_state=json.dumps(shared_state, ensure_ascii=False),
                role=role,
                round=round_num,
                input=input_text,
                game_rules=game_rules,
                player_index=player_index
            )

        template = (self.DEFAULT_TURN_BASED_PARTICIPANT_PROMPT
                    if turn_strategy == "turn_based"
                    else self.DEFAULT_PARTICIPANT_PROMPT)

        return template.format(
            game_rules=game_rules or input_text,
            input=input_text,
            shared_state=json.dumps(shared_state, ensure_ascii=False),
            role=role,
            player_index=player_index,
            round=round_num
        )

    def _build_referee_prompt(self, collab: CollaborationResponse, input_text: str,
                               shared_state: dict, round_actions: str,
                               game_rules: str) -> str:
        """Build prompt for the referee agent"""
        config = collab.config_json
        custom_prompt = config.get("referee_prompt")

        template = custom_prompt or self.DEFAULT_REFEREE_PROMPT

        return template.format(
            game_rules=game_rules or input_text,
            input=input_text,
            shared_state=json.dumps(shared_state, ensure_ascii=False),
            round_actions=round_actions
        )

    def _parse_referee_output(self, output: str) -> dict:
        """Parse referee's structured JSON output"""
        # Try to extract JSON from the output (may be wrapped in markdown code block)
        text = output.strip()

        # Remove markdown code block if present
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
            # Ensure required fields
            return {
                "round_result": result.get("round_result", ""),
                "updated_state": result.get("updated_state", {}),
                "winner": result.get("winner"),
                "game_over": bool(result.get("game_over", False))
            }
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse referee output as JSON: {output[:200]}")
            # Fallback: treat as plain text result
            return {
                "round_result": output,
                "updated_state": {},
                "winner": None,
                "game_over": False
            }

    async def execute(self, collab: CollaborationResponse, input_text: str) -> A2ATask:
        task = A2ATask(
            id=str(uuid.uuid4()),
            input=input_text,
            status=A2ATaskStatus(state=A2ATaskStatusState.RUNNING)
        )

        await self._create_task_record(collab.id, task)

        try:
            config = collab.config_json
            turn_strategy = config.get("turn_strategy", "simultaneous")
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

            # Build participant order for turn_based
            if turn_strategy == "turn_based":
                if not participant_order:
                    participant_order = [p[1] for p in participants]
                # Build role -> agent mapping
                order_map = {}
                for agent, indexed_role, idx in participants:
                    order_map[indexed_role] = agent
                    # Also map by original role
                    order_map[agent.role] = agent

            task.add_message(A2AMessageRole.USER, f"Game start: {input_text}")

            for round_num in range(1, max_rounds + 1):
                logger.info(f"Game round {round_num}/{max_rounds} (strategy: {turn_strategy})")

                round_actions = []

                if turn_strategy == "simultaneous":
                    # All participants act in parallel
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

                    for i, result in enumerate(results):
                        agent, indexed_role, idx, _ = tasks[i]
                        if isinstance(result, Exception):
                            action = f"[{indexed_role} failed: {str(result)}]"
                        else:
                            action = result.output or ""
                        round_actions.append(f"{indexed_role}: {action}")
                        task.add_message(A2AMessageRole.AGENT,
                                         f"[Round {round_num}] {indexed_role}: {action}")

                else:  # turn_based
                    # One participant acts per round
                    role_key = participant_order[(round_num - 1) % len(participant_order)]
                    agent = order_map.get(role_key)
                    if not agent:
                        raise ValueError(f"No agent found for role: {role_key}")

                    # Find the index for this role
                    idx = next((i for a, r, i in participants if r == role_key or a.role == role_key), 0)

                    prompt = self._build_participant_prompt(
                        collab, input_text, shared_state, role_key, idx, round_num, turn_strategy)
                    agent_task = A2ATask(id=str(uuid.uuid4()), input=prompt)
                    result = await agent_registry.call_agent(agent.agent_id, agent_task)

                    action = result.output or ""
                    round_actions.append(f"{role_key}: {action}")
                    task.add_message(A2AMessageRole.AGENT,
                                     f"[Round {round_num}] {role_key}: {action}")

                # Referee judges the round
                if referee_enabled and referee_agent:
                    referee_prompt = self._build_referee_prompt(
                        collab, input_text, shared_state,
                        "\n".join(round_actions), game_rules)
                    referee_task = A2ATask(id=str(uuid.uuid4()), input=referee_prompt)
                    referee_result = await agent_registry.call_agent(referee_agent.agent_id, referee_task)

                    ruling = self._parse_referee_output(referee_result.output or "")
                    task.add_message(A2AMessageRole.AGENT,
                                     f"[Round {round_num}] Referee: {ruling['round_result']}")

                    # Update shared state from referee ruling
                    if ruling["updated_state"]:
                        shared_state.update(ruling["updated_state"])
                    shared_state[f"round_{round_num}_result"] = ruling["round_result"]

                    # Check if game is over
                    if ruling["game_over"]:
                        winner = ruling.get("winner")
                        if winner:
                            task.set_completed(f"游戏结束，{winner} 获胜！{ruling['round_result']}")
                        else:
                            task.set_completed(f"游戏结束。{ruling['round_result']}")
                        task.add_message(A2AMessageRole.AGENT,
                                         f"游戏结束: {ruling['round_result']}")
                        break
                else:
                    # No referee: legacy behavior, just store actions
                    for action_line in round_actions:
                        shared_state[f"round_{round_num}_{action_line.split(':')[0].strip()}"] = action_line

                    # Legacy termination check
                    termination_conditions = config.get("termination_conditions", [])
                    for action_line in round_actions:
                        role_part = action_line.split(":")[0].strip()
                        content_part = ":".join(action_line.split(":")[1:]).strip()
                        terminated, msg = self._check_termination(
                            termination_conditions, content_part, role_part, round_num)
                        if terminated:
                            task.set_completed(f"博弈结束，第 {round_num} 轮，{msg}")
                            task.add_message(A2AMessageRole.AGENT, f"终止条件触发：{msg}")
                            break
                    else:
                        continue
                    break
            else:
                # Max rounds reached - game ended without a winner
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
        task = A2ATask(
            id=str(uuid.uuid4()),
            input=input_text,
            status=A2ATaskStatus(state=A2ATaskStatusState.RUNNING)
        )

        await self._create_task_record(collab.id, task)

        try:
            yield {
                "type": "task_start",
                "task_id": task.id,
                "input": input_text,
                "mode": "game"
            }

            config = collab.config_json
            turn_strategy = config.get("turn_strategy", "simultaneous")
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

            # Build participant order for turn_based
            if turn_strategy == "turn_based":
                if not participant_order:
                    participant_order = [p[1] for p in participants]
                order_map = {}
                for agent, indexed_role, idx in participants:
                    order_map[indexed_role] = agent
                    order_map[agent.role] = agent

            # Emit game start with strategy info
            yield {
                "type": "game_start",
                "shared_state": shared_state,
                "participants": [p[1] for p in participants],
                "turn_strategy": turn_strategy,
                "referee_enabled": referee_enabled
            }

            task.add_message(A2AMessageRole.USER, f"Game start: {input_text}")

            for round_num in range(1, max_rounds + 1):
                yield {
                    "type": "round_start",
                    "round": round_num,
                    "max_rounds": max_rounds
                }

                round_actions = []

                if turn_strategy == "simultaneous":
                    # All participants act in parallel
                    tasks = []
                    for agent, indexed_role, idx in participants:
                        prompt = self._build_participant_prompt(
                            collab, input_text, shared_state, indexed_role, idx, round_num, turn_strategy)
                        t = A2ATask(id=str(uuid.uuid4()), input=prompt)
                        tasks.append((agent, indexed_role, idx, t))

                    # Emit all agent_start events
                    for agent, indexed_role, idx, _ in tasks:
                        yield {
                            "type": "agent_start",
                            "agent_id": agent.agent_id,
                            "role": indexed_role,
                            "round": round_num
                        }

                    # Call all agents in parallel
                    results = await asyncio.gather(
                        *[agent_registry.call_agent(a.agent_id, t) for a, _, _, t in tasks],
                        return_exceptions=True
                    )

                    # Emit all results
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

                else:  # turn_based
                    role_key = participant_order[(round_num - 1) % len(participant_order)]
                    agent = order_map.get(role_key)
                    if not agent:
                        yield {"type": "task_failed", "error": f"No agent found for role: {role_key}"}
                        return

                    idx = next((i for a, r, i in participants if r == role_key or a.role == role_key), 0)

                    prompt = self._build_participant_prompt(
                        collab, input_text, shared_state, role_key, idx, round_num, turn_strategy)

                    yield {
                        "type": "agent_start",
                        "agent_id": agent.agent_id,
                        "role": role_key,
                        "round": round_num
                    }

                    agent_task = A2ATask(id=str(uuid.uuid4()), input=prompt)
                    result = await agent_registry.call_agent(agent.agent_id, agent_task)
                    action = result.output or ""
                    round_actions.append(f"{role_key}: {action}")

                    yield {
                        "type": "agent_message",
                        "agent_id": agent.agent_id,
                        "role": role_key,
                        "content": action,
                        "round": round_num
                    }
                    yield {"type": "agent_done", "agent_id": agent.agent_id, "round": round_num}

                # Referee judges the round
                if referee_enabled and referee_agent:
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

                    # Update shared state
                    if ruling["updated_state"]:
                        shared_state.update(ruling["updated_state"])
                    shared_state[f"round_{round_num}_result"] = ruling["round_result"]

                    yield {
                        "type": "shared_state_update",
                        "shared_state": shared_state,
                        "round": round_num
                    }

                    # Round end with result
                    yield {
                        "type": "round_end",
                        "round": round_num,
                        "passed": not ruling["game_over"],
                        "round_result": ruling["round_result"],
                        "winner": ruling.get("winner"),
                        "game_over": ruling["game_over"]
                    }

                    # Check if game is over
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
                    # No referee: legacy behavior
                    for action_line in round_actions:
                        role_part = action_line.split(":")[0].strip()
                        content_part = ":".join(action_line.split(":")[1:]).strip()
                        shared_state[f"round_{round_num}_{role_part}_output"] = content_part

                    yield {
                        "type": "shared_state_update",
                        "shared_state": shared_state,
                        "round": round_num
                    }

                    termination_conditions = config.get("termination_conditions", [])
                    terminated = False
                    for action_line in round_actions:
                        role_part = action_line.split(":")[0].strip()
                        content_part = ":".join(action_line.split(":")[1:]).strip()
                        terminated, msg = self._check_termination(
                            termination_conditions, content_part, role_part, round_num)
                        if terminated:
                            yield {"type": "termination", "round": round_num, "message": msg}
                            task.set_completed(f"博弈结束，第 {round_num} 轮，{msg}")
                            break

                    if terminated:
                        break

                    yield {"type": "round_end", "round": round_num, "passed": True}
            else:
                # Max rounds reached - game ended without a winner
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
            yield {
                "type": "task_failed",
                "task_id": task.id,
                "error": str(e)
            }

    def _check_termination(
        self, conditions: list, output: str, current_role: str, round_num: int
    ) -> tuple:
        """Legacy termination check (used when referee is disabled)"""
        for condition in conditions:
            cond_type = condition.get("type")

            if cond_type == "content_match":
                keyword = condition.get("keyword", "")
                agent_role = condition.get("agent_role")
                if agent_role and agent_role != current_role:
                    continue
                if keyword and keyword in output:
                    return True, f"{current_role} 输出包含关键词 '{keyword}'"

            elif cond_type == "max_rounds":
                pass

        return False, ""

    async def _create_task_record(self, collab_id: str, task: A2ATask):
        """Create task record in database"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()
        try:
            now = datetime.utcnow().isoformat()
            await db.execute("""
            INSERT INTO collaboration_tasks
            (id, collaboration_id, task_id, input, output, status, messages_json, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                collab_id,
                task.id,
                task.input,
                task.output,
                task.status.state.value,
                json.dumps([m.dict() for m in task.messages]),
                now,
                None
            ))
            await db.commit()
        finally:
            await db.disconnect()

    async def _update_task_record(self, task: A2ATask, completed: bool = False):
        """Update task record in database"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()
        try:
            completed_at = datetime.utcnow().isoformat() if completed else None
            await db.execute("""
            UPDATE collaboration_tasks
            SET output = ?, status = ?, messages_json = ?, completed_at = ?
            WHERE task_id = ?
            """, (
                task.output,
                task.status.state.value,
                json.dumps([m.dict() for m in task.messages]),
                completed_at,
                task.id
            ))
            await db.commit()
        finally:
            await db.disconnect()


class PipelineCollaboration(BaseCollaborationMode):
    """Pipeline mode: agents execute sequentially, each agent's output feeds into the next.

    Like an assembly line: Worker1 → Worker2 → Worker3 → Final Output.
    No central coordinator needed — data flows naturally through the chain.
    """

    DEFAULT_STEP_PROMPT = """你是一个流水线处理步骤。

原始任务：{input}
{context}
你当前的职责：{step_description}

请基于以上信息进行处理，输出你的结果。"""

    async def execute(self, collab: CollaborationResponse, input_text: str) -> A2ATask:
        task = A2ATask(
            id=str(uuid.uuid4()),
            input=input_text,
            status=A2ATaskStatus(state=A2ATaskStatusState.RUNNING)
        )
        await self._create_task_record(collab.id, task)

        try:
            workers = [a for a in collab.agents if a.role == "worker"]
            if not workers:
                raise ValueError("No worker agents found in pipeline collaboration")

            config = collab.config_json
            pass_context = config.get("pass_context", True)
            custom_template = config.get("step_prompt_template")

            current_output = input_text
            all_outputs = []

            for i, worker in enumerate(workers):
                step_desc = worker.config_json.get("description", f"步骤 {i+1}")
                context = ""
                if pass_context and all_outputs:
                    context = "前序步骤的输出：\n" + "\n---\n".join(
                        f"[步骤{j+1}] {out}" for j, out in enumerate(all_outputs)
                    )
                elif all_outputs:
                    context = f"上一步的输出：\n{all_outputs[-1]}"

                if custom_template:
                    prompt = custom_template.format(
                        input=input_text, step_description=step_desc,
                        prev_output=all_outputs[-1] if all_outputs else "",
                        context=context
                    )
                else:
                    prompt = self.DEFAULT_STEP_PROMPT.format(
                        input=input_text, step_description=step_desc, context=context
                    )

                agent_task = A2ATask(id=str(uuid.uuid4()), input=prompt)
                result = await agent_registry.call_agent(worker.agent_id, agent_task)
                current_output = result.output or ""
                all_outputs.append(current_output)

                task.add_message(A2AMessageRole.AGENT,
                                 f"[Step {i+1}] {worker.agent_id}: {current_output}")

            task.set_completed(current_output)
            task.add_message(A2AMessageRole.AGENT, current_output)

            await self._update_task_record(task, completed=True)
            await collaboration_service.increment_usage(collab.id)
            return task

        except Exception as e:
            logger.error(f"Pipeline collaboration failed: {e}", exc_info=True)
            task.set_failed(str(e))
            await self._update_task_record(task, completed=True)
            return task

    async def execute_stream(self, collab: CollaborationResponse, input_text: str):
        task = A2ATask(
            id=str(uuid.uuid4()),
            input=input_text,
            status=A2ATaskStatus(state=A2ATaskStatusState.RUNNING)
        )
        await self._create_task_record(collab.id, task)

        try:
            yield {"type": "task_start", "task_id": task.id, "input": input_text, "mode": "pipeline"}

            workers = [a for a in collab.agents if a.role == "worker"]
            if not workers:
                yield {"type": "task_failed", "error": "No worker agents found"}
                return

            config = collab.config_json
            pass_context = config.get("pass_context", True)
            custom_template = config.get("step_prompt_template")

            current_output = input_text
            all_outputs = []

            for i, worker in enumerate(workers):
                step_desc = worker.config_json.get("description", f"步骤 {i+1}")
                context = ""
                if pass_context and all_outputs:
                    context = "前序步骤的输出：\n" + "\n---\n".join(
                        f"[步骤{j+1}] {out}" for j, out in enumerate(all_outputs)
                    )
                elif all_outputs:
                    context = f"上一步的输出：\n{all_outputs[-1]}"

                if custom_template:
                    prompt = custom_template.format(
                        input=input_text, step_description=step_desc,
                        prev_output=all_outputs[-1] if all_outputs else "",
                        context=context
                    )
                else:
                    prompt = self.DEFAULT_STEP_PROMPT.format(
                        input=input_text, step_description=step_desc, context=context
                    )

                yield {
                    "type": "agent_start",
                    "agent_id": worker.agent_id,
                    "role": "worker",
                    "round": i + 1,
                    "step": i + 1,
                    "total_steps": len(workers)
                }

                agent_task = A2ATask(id=str(uuid.uuid4()), input=prompt)
                result = await agent_registry.call_agent(worker.agent_id, agent_task)
                current_output = result.output or ""
                all_outputs.append(current_output)

                task.add_message(A2AMessageRole.AGENT,
                                 f"[Step {i+1}] {worker.agent_id}: {current_output}")

                yield {
                    "type": "agent_message",
                    "agent_id": worker.agent_id,
                    "role": "worker",
                    "content": current_output,
                    "round": i + 1,
                    "step": i + 1
                }
                yield {"type": "agent_done", "agent_id": worker.agent_id, "round": i + 1}

            task.set_completed(current_output)
            task.add_message(A2AMessageRole.AGENT, current_output)

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
            logger.error(f"Pipeline collaboration failed: {e}", exc_info=True)
            task.set_failed(str(e))
            await self._update_task_record(task, completed=True)
            yield {"type": "task_failed", "task_id": task.id, "error": str(e)}

    async def _create_task_record(self, collab_id: str, task: A2ATask):
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()
        try:
            now = datetime.utcnow().isoformat()
            await db.execute("""
            INSERT INTO collaboration_tasks
            (id, collaboration_id, task_id, input, output, status, messages_json, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()), collab_id, task.id, task.input, task.output,
                task.status.state.value, json.dumps([m.dict() for m in task.messages]),
                now, None
            ))
            await db.commit()
        finally:
            await db.disconnect()

    async def _update_task_record(self, task: A2ATask, completed: bool = False):
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()
        try:
            completed_at = datetime.utcnow().isoformat() if completed else None
            await db.execute("""
            UPDATE collaboration_tasks
            SET output = ?, status = ?, messages_json = ?, completed_at = ?
            WHERE task_id = ?
            """, (
                task.output, task.status.state.value,
                json.dumps([m.dict() for m in task.messages]),
                completed_at, task.id
            ))
            await db.commit()
        finally:
            await db.disconnect()


class VotingCollaboration(BaseCollaborationMode):
    """Voting/Ensemble mode: multiple agents independently answer the same question,
    then an aggregator consolidates the results.

    Strategies:
    - majority: pick the most common answer
    - best_of: aggregator picks the best answer
    - weighted: weighted by voter priority
    """

    DEFAULT_AGGREGATOR_PROMPT = """你是答案聚合器。多个独立Agent对同一个问题给出了各自的回答。

原始问题：{input}

各Agent的回答：
{votes}

请根据以上回答，综合分析并给出最终的、最准确的答案。如果多数Agent意见一致，采用多数意见；如果意见分歧，请分析各方理由并给出最佳判断。

请直接输出最终答案。"""

    async def execute(self, collab: CollaborationResponse, input_text: str) -> A2ATask:
        task = A2ATask(
            id=str(uuid.uuid4()),
            input=input_text,
            status=A2ATaskStatus(state=A2ATaskStatusState.RUNNING)
        )
        await self._create_task_record(collab.id, task)

        try:
            voters = [a for a in collab.agents if a.role == "voter"]
            aggregator = next((a for a in collab.agents if a.role == "aggregator"), None)

            if not voters:
                raise ValueError("No voter agents found in voting collaboration")

            config = collab.config_json
            strategy = config.get("strategy", "best_of")

            # Step 1: All voters answer independently in parallel
            tasks = []
            for voter in voters:
                t = A2ATask(id=str(uuid.uuid4()), input=input_text)
                tasks.append((voter, t))

            results = await asyncio.gather(
                *[agent_registry.call_agent(v.agent_id, t) for v, t in tasks],
                return_exceptions=True
            )

            votes = []
            for i, result in enumerate(results):
                voter = tasks[i][0]
                if isinstance(result, Exception):
                    votes.append((voter, f"[Failed: {str(result)}]"))
                else:
                    votes.append((voter, result.output or ""))

            for voter, answer in votes:
                task.add_message(A2AMessageRole.AGENT,
                                 f"[Vote] {voter.agent_id}: {answer}")

            # Step 2: Aggregate results
            if aggregator:
                final_output = await self._aggregate_with_agent(
                    aggregator, input_text, votes, config)
            else:
                final_output = self._aggregate_simple(votes, strategy)

            task.set_completed(final_output)
            task.add_message(A2AMessageRole.AGENT, final_output)

            await self._update_task_record(task, completed=True)
            await collaboration_service.increment_usage(collab.id)
            return task

        except Exception as e:
            logger.error(f"Voting collaboration failed: {e}", exc_info=True)
            task.set_failed(str(e))
            await self._update_task_record(task, completed=True)
            return task

    async def execute_stream(self, collab: CollaborationResponse, input_text: str):
        task = A2ATask(
            id=str(uuid.uuid4()),
            input=input_text,
            status=A2ATaskStatus(state=A2ATaskStatusState.RUNNING)
        )
        await self._create_task_record(collab.id, task)

        try:
            yield {"type": "task_start", "task_id": task.id, "input": input_text, "mode": "voting"}

            voters = [a for a in collab.agents if a.role == "voter"]
            aggregator = next((a for a in collab.agents if a.role == "aggregator"), None)

            if not voters:
                yield {"type": "task_failed", "error": "No voter agents found"}
                return

            config = collab.config_json
            strategy = config.get("strategy", "best_of")

            # Step 1: All voters answer in parallel
            for voter in voters:
                yield {
                    "type": "agent_start",
                    "agent_id": voter.agent_id,
                    "role": "voter",
                    "round": 1
                }

            tasks = [(v, A2ATask(id=str(uuid.uuid4()), input=input_text)) for v in voters]
            results = await asyncio.gather(
                *[agent_registry.call_agent(v.agent_id, t) for v, t in tasks],
                return_exceptions=True
            )

            votes = []
            for i, result in enumerate(results):
                voter = tasks[i][0]
                if isinstance(result, Exception):
                    answer = f"[Failed: {str(result)}]"
                else:
                    answer = result.output or ""
                votes.append((voter, answer))

                yield {
                    "type": "agent_message",
                    "agent_id": voter.agent_id,
                    "role": "voter",
                    "content": answer,
                    "round": 1
                }
                yield {"type": "agent_done", "agent_id": voter.agent_id, "round": 1}

            # Step 2: Aggregate
            if aggregator:
                yield {
                    "type": "agent_start",
                    "agent_id": aggregator.agent_id,
                    "role": "aggregator",
                    "round": 2
                }

                final_output = await self._aggregate_with_agent(
                    aggregator, input_text, votes, config)

                yield {
                    "type": "agent_message",
                    "agent_id": aggregator.agent_id,
                    "role": "aggregator",
                    "content": final_output,
                    "round": 2
                }
                yield {"type": "agent_done", "agent_id": aggregator.agent_id, "round": 2}
            else:
                final_output = self._aggregate_simple(votes, strategy)

            task.set_completed(final_output)
            task.add_message(A2AMessageRole.AGENT, final_output)

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
            logger.error(f"Voting collaboration failed: {e}", exc_info=True)
            task.set_failed(str(e))
            await self._update_task_record(task, completed=True)
            yield {"type": "task_failed", "task_id": task.id, "error": str(e)}

    async def _aggregate_with_agent(self, aggregator, input_text, votes, config):
        """Use an aggregator agent to produce final answer"""
        custom_prompt = config.get("aggregator_prompt")
        votes_text = "\n".join(
            f"Agent {voter.agent_id} (优先级: {voter.priority}): {answer}"
            for voter, answer in votes
        )

        if custom_prompt:
            prompt = custom_prompt.format(input=input_text, votes=votes_text)
        else:
            prompt = self.DEFAULT_AGGREGATOR_PROMPT.format(input=input_text, votes=votes_text)

        agg_task = A2ATask(id=str(uuid.uuid4()), input=prompt)
        result = await agent_registry.call_agent(aggregator.agent_id, agg_task)
        return result.output or "No aggregated output"

    def _aggregate_simple(self, votes, strategy):
        """Simple aggregation without an aggregator agent"""
        answers = [answer for _, answer in votes if not answer.startswith("[Failed")]

        if not answers:
            return "All voters failed"

        if strategy == "majority":
            # Count occurrences of each answer
            from collections import Counter
            counter = Counter(answers)
            most_common = counter.most_common(1)
            return most_common[0][0] if most_common else answers[0]

        elif strategy == "weighted":
            # Priority-weighted: just return the highest-priority voter's answer
            weighted = sorted(votes, key=lambda x: x[0].priority, reverse=True)
            return weighted[0][1] if weighted else answers[0]

        else:  # best_of fallback
            return answers[0] if answers else "No answers"

    async def _create_task_record(self, collab_id: str, task: A2ATask):
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()
        try:
            now = datetime.utcnow().isoformat()
            await db.execute("""
            INSERT INTO collaboration_tasks
            (id, collaboration_id, task_id, input, output, status, messages_json, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()), collab_id, task.id, task.input, task.output,
                task.status.state.value, json.dumps([m.dict() for m in task.messages]),
                now, None
            ))
            await db.commit()
        finally:
            await db.disconnect()

    async def _update_task_record(self, task: A2ATask, completed: bool = False):
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()
        try:
            completed_at = datetime.utcnow().isoformat() if completed else None
            await db.execute("""
            UPDATE collaboration_tasks
            SET output = ?, status = ?, messages_json = ?, completed_at = ?
            WHERE task_id = ?
            """, (
                task.output, task.status.state.value,
                json.dumps([m.dict() for m in task.messages]),
                completed_at, task.id
            ))
            await db.commit()
        finally:
            await db.disconnect()


class CollaborationEngine:
    """Main engine that dispatches to appropriate collaboration mode"""

    def __init__(self):
        self.modes = {
            CollaborationMode.SUPERVISOR: SupervisorCollaboration(),
            CollaborationMode.PIPELINE: PipelineCollaboration(),
            CollaborationMode.VOTING: VotingCollaboration(),
            CollaborationMode.ADVERSARIAL_GEN_DIS: GenerateDiscriminateCollaboration(),
            CollaborationMode.ADVERSARIAL_GAME: GameCollaboration(),
        }

    async def execute(self, collab_id: str, input_text: str) -> dict:
        """Execute a collaboration"""
        # Get collaboration config
        collab = await collaboration_service.get(collab_id)
        if not collab:
            raise ValueError(f"Collaboration {collab_id} not found")

        if not collab.enabled:
            raise ValueError(f"Collaboration {collab_id} is disabled")

        # Get mode handler
        mode_handler = self.modes.get(collab.mode)
        if not mode_handler:
            raise ValueError(f"Unsupported collaboration mode: {collab.mode}")

        # Execute
        task = await mode_handler.execute(collab, input_text)

        # Return result as dict
        return {
            "task_id": task.id,
            "collaboration_id": collab_id,
            "input": task.input,
            "output": task.output,
            "status": task.status.state.value,
            "messages": [m.dict() for m in task.messages],
            "started_at": task.created_at,
            "completed_at": task.updated_at if task.status.state.value in ["completed", "failed"] else None
        }


# Global collaboration engine instance
collaboration_engine = CollaborationEngine()
