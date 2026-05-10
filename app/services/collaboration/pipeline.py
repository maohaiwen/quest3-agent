"""Pipeline collaboration mode - agents execute sequentially, output feeds into next"""
import logging
import uuid
from typing import List, Dict, Any

from app.models.a2a import A2ATask, A2AMessageRole
from app.models.collaboration import CollaborationResponse, IterationConfig
from app.services.collaboration.base import BaseCollaborationMode
from app.services.collaboration_service import collaboration_service
from app.services.agent_registry import agent_registry

logger = logging.getLogger(__name__)


class PipelineCollaboration(BaseCollaborationMode):
    """Pipeline mode: agents execute sequentially, each agent's output feeds into the next.

    Like an assembly line: Worker1 → Worker2 → Worker3 → Final Output.
    No central coordinator needed — data flows naturally through the chain.
    """

    def _build_pipeline_prompt(
        self, step_index: int, input_text: str, step_desc: str,
        all_outputs: list, pass_context: bool, custom_instruction: str = None,
        iteration_enabled: bool = False
    ) -> str:
        """Build the prompt for a pipeline step.

        User's custom instruction (step_prompt_template) is always used as a prefix,
        then system appends context automatically. No placeholders needed.
        """
        prefix = f"{custom_instruction}\n\n" if custom_instruction else ""
        artifact_instruction = self.get_artifact_format_instruction() if iteration_enabled else ""

        if not all_outputs:
            return f"""{prefix}你是一个流水线处理步骤。

原始任务：{input_text}
你当前的职责：{step_desc}
{artifact_instruction}
请根据以上任务和职责进行处理，输出你的结果。"""

        earlier_context = ""
        if pass_context and len(all_outputs) > 1:
            earlier_context = "更早步骤的输出（仅供参考）：\n" + "\n---\n".join(
                f"[步骤{j+1}] {out}" for j, out in enumerate(all_outputs[:-1])
            ) + "\n"

        return f"""{prefix}你是一个流水线处理步骤，你需要基于上一步的输出继续处理。

原始任务：{input_text}
{earlier_context}上一步的输出（你必须基于此继续处理）：
{all_outputs[-1]}
你当前的职责：{step_desc}
{artifact_instruction}
重要：你必须基于上一步的输出结果继续处理，而不是重新开始原始任务。只输出你的处理结果，不要重复上一步的内容。"""

    async def execute(self, collab: CollaborationResponse, input_text: str) -> A2ATask:
        task = self._create_task(input_text)
        await self._create_task_record(collab.id, task)

        try:
            workers = [a for a in collab.agents if a.role == "worker"]
            if not workers:
                raise ValueError("No worker agents found in pipeline collaboration")

            config = collab.config_json
            pass_context = config.get("pass_context", True)
            custom_instruction = config.get("step_prompt_template")
            iteration_enabled = IterationConfig(**config.get("iteration", {})).enabled

            all_outputs = []

            for i, worker in enumerate(workers):
                step_desc = worker.config_json.get("description", f"步骤 {i+1}")
                prompt = self._build_pipeline_prompt(
                    i, input_text, step_desc, all_outputs,
                    pass_context, custom_instruction, iteration_enabled
                )

                agent_task = A2ATask(id=str(uuid.uuid4()), input=prompt)
                result = await agent_registry.call_agent(worker.agent_id, agent_task)
                current_output = result.output or ""
                all_outputs.append(current_output)

                task.add_message(A2AMessageRole.AGENT,
                                 f"[Step {i+1}] {worker.agent_id}: {current_output}")

            task.set_completed(all_outputs[-1] if all_outputs else "")
            task.add_message(A2AMessageRole.AGENT, all_outputs[-1] if all_outputs else "")

            await self._update_task_record(task, completed=True)
            await collaboration_service.increment_usage(collab.id)
            return task

        except Exception as e:
            logger.error(f"Pipeline collaboration failed: {e}", exc_info=True)
            task.set_failed(str(e))
            await self._update_task_record(task, completed=True)
            return task

    async def execute_stream(self, collab: CollaborationResponse, input_text: str):
        task = self._create_task(input_text)
        if not self._skip_task_record:
            await self._create_task_record(collab.id, task)

        try:
            tid = self._shared_task_id or task.id
            yield {"type": "task_start", "task_id": tid, "input": input_text, "mode": "pipeline"}

            workers = [a for a in collab.agents if a.role == "worker"]
            if not workers:
                yield {"type": "task_failed", "error": "No worker agents found"}
                return

            config = collab.config_json
            pass_context = config.get("pass_context", True)
            custom_instruction = config.get("step_prompt_template")
            iteration_enabled = IterationConfig(**config.get("iteration", {})).enabled

            all_outputs = []

            for i, worker in enumerate(workers):
                step_desc = worker.config_json.get("description", f"步骤 {i+1}")
                prompt = self._build_pipeline_prompt(
                    i, input_text, step_desc, all_outputs,
                    pass_context, custom_instruction, iteration_enabled
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
                current_output = ""

                async for sub_event in agent_registry.call_agent_stream(worker.agent_id, agent_task):
                    # Forward sub-events with agent_id prefix
                    yield {
                        "type": f"agent_{sub_event['type']}",
                        "agent_id": worker.agent_id,
                        "role": "worker",
                        "round": i + 1,
                        **{k: v for k, v in sub_event.items() if k != "type"},
                    }
                    # Collect final output from content events
                    if sub_event.get("type") == "content":
                        current_output += sub_event["content"]

                # Fallback: if no content events, read from the completed task
                if not current_output and agent_task.output:
                    current_output = agent_task.output

                all_outputs.append(current_output)
                task.add_message(A2AMessageRole.AGENT,
                                 f"[Step {i+1}] {worker.agent_id}: {current_output}")

                yield {"type": "agent_done", "agent_id": worker.agent_id, "round": i + 1}

            final_output = all_outputs[-1] if all_outputs else ""
            task.set_completed(final_output)
            task.add_message(A2AMessageRole.AGENT, final_output)

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
            logger.error(f"Pipeline collaboration failed: {e}", exc_info=True)
            task.set_failed(str(e))
            if not self._skip_task_record:
                await self._update_task_record(task, completed=True)
            yield {"type": "task_failed", "task_id": task.id, "error": str(e)}
