"""Supervisor collaboration mode - one supervisor splits task, children execute, then summarize"""
import asyncio
import json
import logging
import re
import uuid
from typing import List, Dict, Any

from app.models.a2a import A2ATask, A2ATaskStatus, A2ATaskStatusState, A2AMessage, A2AMessageRole
from app.models.collaboration import CollaborationResponse, IterationConfig
from app.services.collaboration.base import BaseCollaborationMode
from app.services.collaboration_service import collaboration_service
from app.services.agent_registry import agent_registry

logger = logging.getLogger(__name__)


class SupervisorCollaboration(BaseCollaborationMode):
    """Supervisor mode: one supervisor agent splits task, child agents execute in parallel, then summarize"""

    async def execute(self, collab: CollaborationResponse, input_text: str) -> A2ATask:
        task = self._create_task(input_text)
        await self._create_task_record(collab.id, task)

        try:
            supervisor_agent, child_agents, child_agent_info = self._resolve_agents(collab)
            agent_list_str = self._build_agent_list_str(child_agent_info)

            # Step 1: Supervisor splits the task
            split_prompt = self._build_split_prompt(collab, input_text, agent_list_str)
            split_task = A2ATask(id=str(uuid.uuid4()), input=split_prompt)
            split_result = await agent_registry.call_agent(supervisor_agent.agent_id, split_task)

            sub_tasks = self._parse_subtasks(split_result.output, child_agent_info)

            # Step 2: Execute child agents in parallel or sequence
            parallel = collab.config_json.get("parallel_execution", True)
            iteration_enabled = IterationConfig(**collab.config_json.get("iteration", {})).enabled
            child_results = await self._execute_children(
                sub_tasks, input_text, parallel, task, iteration_enabled
            )

            # Step 3: Supervisor summarizes results
            child_results_str = self._build_child_results_str(sub_tasks, child_results)
            summary_prompt = self._build_summary_prompt(collab, input_text, child_results_str)
            summary_task = A2ATask(id=str(uuid.uuid4()), input=summary_prompt)
            summary_result = await agent_registry.call_agent(supervisor_agent.agent_id, summary_task)

            task.set_completed(summary_result.output or "No summary generated")
            task.add_message(A2AMessageRole.AGENT, summary_result.output or "")

            await self._update_task_record(task, completed=True)
            await collaboration_service.increment_usage(collab.id)
            return task

        except Exception as e:
            logger.error(f"Supervisor collaboration failed: {e}", exc_info=True)
            task.set_failed(str(e))
            await self._update_task_record(task, completed=True)
            return task

    async def execute_stream(self, collab: CollaborationResponse, input_text: str):
        """Execute supervisor mode with SSE event streaming"""
        task = self._create_task(input_text)
        if not self._skip_task_record:
            await self._create_task_record(collab.id, task)

        try:
            if self._skip_task_record:
                yield {
                    "type": "task_start",
                    "task_id": self._shared_task_id or task.id,
                    "input": input_text,
                    "mode": "supervisor"
                }
            else:
                yield {
                    "type": "task_start",
                    "task_id": task.id,
                    "input": input_text,
                    "mode": "supervisor"
                }

            supervisor_agent, child_agents, child_agent_info = self._resolve_agents(collab)
            agent_list_str = self._build_agent_list_str(child_agent_info)

            if not supervisor_agent or not child_agents:
                yield {"type": "task_failed", "error": "Missing supervisor or child agents"}
                return

            # Step 1: Supervisor splits task (streaming)
            yield {
                "type": "agent_start",
                "agent_id": supervisor_agent.agent_id,
                "role": "supervisor",
                "round": 0
            }

            split_prompt = self._build_split_prompt(collab, input_text, agent_list_str)
            split_task = A2ATask(id=str(uuid.uuid4()), input=split_prompt)
            split_output = ""

            async for sub_event in agent_registry.call_agent_stream(supervisor_agent.agent_id, split_task):
                yield {
                    "type": f"agent_{sub_event['type']}",
                    "agent_id": supervisor_agent.agent_id,
                    "role": "supervisor",
                    "round": 0,
                    **{k: v for k, v in sub_event.items() if k != "type"},
                }
                if sub_event.get("type") == "content":
                    split_output += sub_event["content"]

            if not split_output and split_task.output:
                split_output = split_task.output

            yield {"type": "agent_done", "agent_id": supervisor_agent.agent_id, "round": 0}

            sub_tasks = self._parse_subtasks(split_output, child_agent_info)

            # Step 2: Execute child agents with streaming
            parallel = collab.config_json.get("parallel_execution", True)
            iteration_enabled = IterationConfig(**collab.config_json.get("iteration", {})).enabled
            logger.info(f"Supervisor: parsed {len(sub_tasks)} sub-tasks (parallel={parallel})")

            child_results = []

            if parallel and len(sub_tasks) > 1:
                # For parallel: emit agent_start for all, then run in parallel
                # Use asyncio.Queue to multiplex streams from parallel agents
                for idx, (child_agent, sub_input) in enumerate(sub_tasks):
                    yield {
                        "type": "agent_start",
                        "agent_id": child_agent.agent_id,
                        "role": "child",
                        "round": idx + 1
                    }

                # Create a queue for multiplexing events from parallel agents
                event_queue: asyncio.Queue = asyncio.Queue()
                pending_count = len(sub_tasks)

                async def _run_child_stream(child_agent, sub_input, idx):
                    """Run a child agent's streaming execution and push events to queue."""
                    enhanced_input = self._enhance_child_task(sub_input, input_text, iteration_enabled)
                    t = A2ATask(id=str(uuid.uuid4()), input=enhanced_input)
                    output = ""
                    try:
                        async for sub_event in agent_registry.call_agent_stream(child_agent.agent_id, t):
                            await event_queue.put({
                                "type": f"agent_{sub_event['type']}",
                                "agent_id": child_agent.agent_id,
                                "role": "child",
                                "round": idx + 1,
                                **{k: v for k, v in sub_event.items() if k != "type"},
                            })
                            if sub_event.get("type") == "content":
                                output += sub_event["content"]
                    except Exception as e:
                        await event_queue.put({
                            "type": "agent_error",
                            "agent_id": child_agent.agent_id,
                            "message": str(e),
                        })
                    if not output and t.output:
                        output = t.output
                    await event_queue.put({"type": "_child_done", "agent_id": child_agent.agent_id, "output": output})

                # Launch all child streams as tasks
                child_tasks = []
                for idx, (child_agent, sub_input) in enumerate(sub_tasks):
                    child_tasks.append(asyncio.create_task(
                        _run_child_stream(child_agent, sub_input, idx)
                    ))

                # Consume events from queue and yield them
                done_count = 0
                agent_round_map = {ca.agent_id: idx + 1 for idx, (ca, _) in enumerate(sub_tasks)}
                while done_count < pending_count:
                    event = await event_queue.get()
                    if event["type"] == "_child_done":
                        done_count += 1
                        child_results.append(event["output"])
                        yield {"type": "agent_done", "agent_id": event["agent_id"], "round": agent_round_map.get(event["agent_id"], 1)}
                    else:
                        yield event

                # Wait for all tasks to complete (they should be done by now)
                await asyncio.gather(*child_tasks, return_exceptions=True)

            else:
                # Sequential execution — stream directly
                for idx, (child_agent, sub_input) in enumerate(sub_tasks):
                    yield {
                        "type": "agent_start",
                        "agent_id": child_agent.agent_id,
                        "role": "child",
                        "round": idx + 1
                    }

                    enhanced_input = self._enhance_child_task(sub_input, input_text, iteration_enabled)
                    t = A2ATask(id=str(uuid.uuid4()), input=enhanced_input)
                    child_output = ""

                    async for sub_event in agent_registry.call_agent_stream(child_agent.agent_id, t):
                        yield {
                            "type": f"agent_{sub_event['type']}",
                            "agent_id": child_agent.agent_id,
                            "role": "child",
                            "round": idx + 1,
                            **{k: v for k, v in sub_event.items() if k != "type"},
                        }
                        if sub_event.get("type") == "content":
                            child_output += sub_event["content"]

                    if not child_output and t.output:
                        child_output = t.output

                    child_results.append(child_output)
                    task.add_message(A2AMessageRole.AGENT,
                                     f"[Child {idx+1}] {child_agent.agent_id}: {child_output}")

                    yield {"type": "agent_done", "agent_id": child_agent.agent_id, "round": idx + 1}

            # Step 3: Supervisor summarizes (streaming)
            yield {
                "type": "agent_start",
                "agent_id": supervisor_agent.agent_id,
                "role": "supervisor",
                "round": 999
            }

            child_results_str = self._build_child_results_str(sub_tasks, child_results)
            summary_prompt = self._build_summary_prompt(collab, input_text, child_results_str)
            summary_task = A2ATask(id=str(uuid.uuid4()), input=summary_prompt)
            summary_output = ""

            async for sub_event in agent_registry.call_agent_stream(supervisor_agent.agent_id, summary_task):
                yield {
                    "type": f"agent_{sub_event['type']}",
                    "agent_id": supervisor_agent.agent_id,
                    "role": "supervisor",
                    "round": 999,
                    **{k: v for k, v in sub_event.items() if k != "type"},
                }
                if sub_event.get("type") == "content":
                    summary_output += sub_event["content"]

            if not summary_output and summary_task.output:
                summary_output = summary_task.output

            task.set_completed(summary_output or "No summary generated")
            task.add_message(A2AMessageRole.AGENT, summary_output or "")

            yield {"type": "agent_done", "agent_id": supervisor_agent.agent_id, "round": 999}

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
            logger.error(f"Supervisor collaboration failed: {e}", exc_info=True)
            task.set_failed(str(e))
            if not self._skip_task_record:
                await self._update_task_record(task, completed=True)
            yield {"type": "task_failed", "task_id": task.id, "error": str(e)}

    # --- Private helpers ---

    def _resolve_agents(self, collab: CollaborationResponse):
        """Get supervisor, child agents, and child agent info"""
        supervisor_agent = next((a for a in collab.agents if a.role == "supervisor"), None)
        child_agents = [a for a in collab.agents if a.role == "child"]

        child_agent_info = []
        for a in child_agents:
            agent_card = agent_registry.get_agent_card(a.agent_id)
            agent_name = agent_card.name if agent_card else a.agent_id
            child_agent_info.append({"agent_id": a.agent_id, "name": agent_name, "config": a})

        return supervisor_agent, child_agents, child_agent_info

    @staticmethod
    def _build_agent_list_str(child_agent_info: list) -> str:
        return chr(10).join(
            f"- [{i+1}] {info['name']} (ID: {info['agent_id']})"
            for i, info in enumerate(child_agent_info)
        )

    @staticmethod
    def _build_split_prompt(collab, input_text, agent_list_str):
        split_prompt = collab.config_json.get("split_prompt")
        if not split_prompt:
            return f"""请将以下任务拆分成多个子任务，分配给以下子Agent：
任务：{input_text}
子Agent列表：
{agent_list_str}
请按以下格式输出每个子任务（每行一个，使用Agent编号或名称）：
[1] 具体任务描述
[2] 具体任务描述
或：
子任务1：分配给 [Agent名称或编号] - 具体任务描述
子任务2：分配给 [Agent名称或编号] - 具体任务描述"""
        return f"""{split_prompt}

当前任务：{input_text}
可分配的子Agent列表：
{agent_list_str}
请按以上格式输出每个子任务，使用Agent编号或名称来分配。"""

    @staticmethod
    def _build_summary_prompt(collab, input_text, child_results_str):
        summary_prompt = collab.config_json.get("summary_prompt")
        if not summary_prompt:
            return f"""以下是各子Agent的执行结果，请汇总为最终答案：
原始任务：{input_text}
子任务结果：
{child_results_str}
请输出最终的汇总结果："""
        return f"""{summary_prompt}

【重要】你必须基于以下子任务执行结果来汇总，不要忽略这些内容：

原始任务：{input_text}

各子Agent的执行结果如下：
{child_results_str}

请基于以上子任务结果进行整合汇总，直接输出最终内容，不要要求更多信息。"""

    @staticmethod
    def _build_child_results_str(sub_tasks, child_results):
        result_parts = []
        for i in range(len(child_results)):
            agent_card = agent_registry.get_agent_card(sub_tasks[i][0].agent_id)
            agent_name = agent_card.name if agent_card else sub_tasks[i][0].agent_id
            result_parts.append(f"Agent {agent_name}: {child_results[i]}")
        return chr(10).join(result_parts)

    async def _execute_children(self, sub_tasks, input_text, parallel, task, iteration_enabled=False):
        """Execute child agents and return list of result strings (non-streaming)"""
        child_results = []

        if parallel:
            tasks = []
            for child_agent, sub_input in sub_tasks:
                enhanced_input = self._enhance_child_task(sub_input, input_text, iteration_enabled)
                t = A2ATask(id=str(uuid.uuid4()), input=enhanced_input)
                tasks.append(agent_registry.call_agent(child_agent.agent_id, t))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Child agent {sub_tasks[i][0].agent_id} failed: {result}")
                    child_results.append(f"[Agent {sub_tasks[i][0].agent_id} failed: {str(result)}]")
                else:
                    child_results.append(result.output or "")
                    await self._update_task_record(result)
        else:
            for child_agent, sub_input in sub_tasks:
                enhanced_input = self._enhance_child_task(sub_input, input_text, iteration_enabled)
                t = A2ATask(id=str(uuid.uuid4()), input=enhanced_input)
                try:
                    result = await agent_registry.call_agent(child_agent.agent_id, t)
                    child_results.append(result.output or "")
                    await self._update_task_record(result)
                except Exception as e:
                    logger.error(f"Child agent {child_agent.agent_id} failed: {e}")
                    child_results.append(f"[Agent {child_agent.agent_id} failed: {str(e)}]")

        return child_results

    def _parse_subtasks(self, split_output: str, child_agent_info: list) -> list:
        """Parse supervisor's split output to get sub-tasks for each child agent."""
        sub_tasks = []
        lines = split_output.split('\n')
        assigned_indices = set()

        # Strategy 1: Match numbered items
        numbered_items = []
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue

            m = re.match(r'^\s*(?:\[|\(|#)?\s*(\d+)\s*(?:\]|\)|\.|[：:.)）])\s*(.*)', line_stripped)
            if not m:
                m = re.match(r'^\s*(?:Agent\s*(\d+)|子任务\s*(\d+))[：:.)\]）]?\s*(.*)', line_stripped)
                if m:
                    idx_str = m.group(1) or m.group(2)
                    m = type('M', (), {'group': lambda self, i: idx_str if i == 1 else line_stripped})()

            if m:
                idx_str = m.group(1)
                task_desc = line_stripped
                try:
                    idx = int(idx_str)
                    if 1 <= idx <= len(child_agent_info):
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

        for slot_idx, task_desc, full_line in numbered_items:
            if slot_idx not in assigned_indices and slot_idx < len(child_agent_info):
                assigned_indices.add(slot_idx)
                info = child_agent_info[slot_idx]
                task_desc = self._clean_task_desc(task_desc)
                sub_tasks.append((info["config"], task_desc))

        # Strategy 2: Match by agent name
        if len(sub_tasks) < len(child_agent_info):
            agent_name_usage = {}
            for line in lines:
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                for info in child_agent_info:
                    name = info["name"]
                    if name in line_stripped:
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

        # Strategy 3: Distribute original task to remaining slots
        if len(sub_tasks) < len(child_agent_info):
            for i, info in enumerate(child_agent_info):
                if i not in assigned_indices:
                    sub_tasks.append((info["config"], f"请协助完成以下任务：\n{split_output}"))

        sub_tasks.sort(key=lambda x: next(
            (i for i, info in enumerate(child_agent_info) if info["config"] == x[0]), 999
        ))
        return sub_tasks

    @staticmethod
    def _clean_task_desc(task_desc: str) -> str:
        task_desc = re.sub(r'\*\*', '', task_desc)
        task_desc = re.sub(r'^子任务\d+[：:]\s*', '', task_desc)
        task_desc = re.sub(r'^Agent\s*\d+\s*[：:.)\)）]?\s*', '', task_desc)
        task_desc = re.sub(r'\([0-9a-f]{8,}\.\.\.\)\s*', '', task_desc)
        return task_desc.strip()

    @staticmethod
    def _enhance_child_task(sub_input: str, original_task: str, iteration_enabled: bool = False) -> str:
        artifact_instruction = BaseCollaborationMode.get_artifact_format_instruction() if iteration_enabled else ""
        return f"""【协作子任务】{sub_input}

原始任务：{original_task}
{artifact_instruction}
重要要求：
1. 你必须使用可用的工具（如web_search搜索资讯、代码解释器获取和分析数据）获取实际数据后再进行分析
2. 不要只输出分析框架或大纲，必须包含具体的数据、数值和分析结论
3. 如果工具调用失败，请尝试不同的搜索关键词或数据获取方式
4. 分析结果必须基于实际获取到的数据，不能凭空编造"""
