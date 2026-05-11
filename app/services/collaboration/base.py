"""Base class for collaboration modes with shared database operations,
iteration capability, artifact management, and human input support"""
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from app.models.a2a import A2ATask, A2ATaskStatus, A2ATaskStatusState, A2AMessage, A2AMessageRole
from app.models.collaboration import (
    CollaborationResponse, CollaborationAgentConfig,
    IterationConfig, Artifact, ArtifactType
)
from app.database.connection import DatabaseConnection
from app.config import settings
from app.utils.timezone import beijing_now

logger = logging.getLogger(__name__)

# Regex for extracting artifacts from agent output
_ARTIFACT_PATTERN = re.compile(r'【产物[：:](.+?)】\s*\n(.*?)(?=【产物[：:]|$)', re.DOTALL)


class BaseCollaborationMode:
    """Base class for collaboration modes.

    Provides shared _create_task_record, _update_task_record,
    iteration loop, artifact extraction/persistence, and evaluation.
    """

    def __init__(self):
        # When True, execute_stream() skips _create_task_record/_update_task_record.
        # Set by execute_stream_with_iteration() so iterations share one task record.
        self._skip_task_record = False
        self._shared_task_id = None

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

    # -------------------------------------------------------------------------
    # Iteration capability
    # -------------------------------------------------------------------------

    async def execute_with_iteration(
        self, collab: CollaborationResponse, input_text: str
    ) -> A2ATask:
        """Execute with iteration loop if configured, otherwise delegate to execute()."""
        iteration_config = IterationConfig(
            **collab.config_json.get("iteration", {})
        )

        if not iteration_config.enabled:
            return await self.execute(collab, input_text)

        context: Dict[str, Any] = {
            "original_input": input_text,
            "history": [],
            "artifacts": [],
        }

        task = None
        for i in range(iteration_config.max_iterations):
            round_num = i + 1
            enhanced_input = self._inject_feedback(input_text, context, round_num)

            logger.info(f"Iteration round {round_num}/{iteration_config.max_iterations}")

            task = await self.execute(collab, enhanced_input)

            # Extract & save artifacts from all agent messages in this round
            round_artifacts = await self._extract_and_save_artifacts(
                task, collab.id, round_num
            )
            context["artifacts"].extend(round_artifacts)

            # Evaluate
            passed, feedback = await self._evaluate(
                task.output or "", iteration_config, context
            )

            task.add_message(
                A2AMessageRole.AGENT,
                f"[迭代评估-第{round_num}轮] {'通过' if passed else '未通过'}。{feedback}"
            )
            await self._update_task_record(task)

            if passed:
                logger.info(f"Iteration passed at round {round_num}")
                return task

            # Record history for next round feedback
            context["history"].append({
                "round": round_num,
                "output": task.output or "",
                "feedback": feedback,
                "artifacts": [
                    {"name": a.name, "type": a.artifact_type.value, "content": a.content}
                    for a in round_artifacts
                ],
            })

        # Reached max iterations — return last task
        logger.warning(f"Reached max iterations ({iteration_config.max_iterations})")
        return task

    async def execute_stream_with_iteration(
        self, collab: CollaborationResponse, input_text: str
    ):
        """Streaming version of execute_with_iteration.

        Creates ONE task record for the entire iteration run.
        Sub-iterations reuse the same task ID — no duplicate records.
        """
        iteration_config = IterationConfig(
            **collab.config_json.get("iteration", {})
        )

        if not iteration_config.enabled:
            async for event in self.execute_stream(collab, input_text):
                yield event
            return

        # Create or reuse task record
        already_skipping = self._skip_task_record  # set by _run_in_background
        main_task = self._create_task(input_text)

        if already_skipping:
            # Reuse existing task record (background continuation)
            main_task.id = self._shared_task_id or main_task.id
        else:
            await self._create_task_record(collab.id, main_task)

        # Tell sub-mode execute_stream to skip task record creation
        self._skip_task_record = True
        self._shared_task_id = main_task.id

        try:
            yield {
                "type": "task_start",
                "task_id": main_task.id,
                "input": input_text,
                "mode": getattr(collab, "mode", "unknown"),
            }

            context: Dict[str, Any] = {
                "original_input": input_text,
                "history": [],
                "artifacts": [],
            }

            task_output = ""
            for i in range(iteration_config.max_iterations):
                round_num = i + 1
                enhanced_input = self._inject_feedback(input_text, context, round_num)

                yield {
                    "type": "iteration_start",
                    "round": round_num,
                    "max_iterations": iteration_config.max_iterations,
                }

                # Run underlying mode — will skip _create_task_record due to flag
                async for event in self.execute_stream(collab, enhanced_input):
                    if event.get("type") == "task_start":
                        # Replace task_start from sub-mode — we already emitted ours
                        continue
                    if event.get("type") == "task_complete":
                        task_output = event.get("output", "")
                    if event.get("type") == "task_failed":
                        # Sub-mode failed
                        main_task.set_failed(event.get("error", "Iteration round failed"))
                        if not already_skipping:
                            await self._update_task_record(main_task, completed=True)
                        yield event
                        return
                    yield event

                # Extract & save artifacts
                sub_task = self._create_task(enhanced_input)
                sub_task.set_completed(task_output)
                round_artifacts = await self._extract_and_save_artifacts(
                    sub_task, collab.id, round_num
                )
                context["artifacts"].extend(round_artifacts)

                # Yield artifact events
                for artifact in round_artifacts:
                    yield {
                        "type": "artifact_created",
                        "artifact_id": artifact.id,
                        "name": artifact.name,
                        "artifact_type": artifact.artifact_type.value,
                        "round": round_num,
                    }

                # Evaluate
                passed, feedback = await self._evaluate(
                    task_output, iteration_config, context
                )

                yield {
                    "type": "iteration_evaluate",
                    "round": round_num,
                    "passed": passed,
                    "feedback": feedback,
                }

                if passed:
                    main_task.set_completed(task_output)
                    main_task.add_message(A2AMessageRole.AGENT, task_output)
                    if not already_skipping:
                        await self._update_task_record(main_task, completed=True)
                        await collaboration_service.increment_usage(collab.id)
                    yield {
                        "type": "iteration_complete",
                        "round": round_num,
                        "passed": True,
                    }
                    yield {
                        "type": "task_complete",
                        "task_id": main_task.id,
                        "status": "completed",
                        "output": task_output,
                        "messages": [m.dict() for m in main_task.messages],
                    }
                    return

                # Not passed — yield feedback event for next round
                yield {
                    "type": "iteration_feedback",
                    "round": round_num,
                    "feedback": feedback,
                    "artifacts_summary": [
                        {"name": a.name, "type": a.artifact_type.value}
                        for a in round_artifacts
                    ],
                }

                context["history"].append({
                    "round": round_num,
                    "output": task_output,
                    "feedback": feedback,
                    "artifacts": [
                        {"name": a.name, "type": a.artifact_type.value, "content": a.content}
                        for a in round_artifacts
                    ],
                })

            # Max iterations reached
            main_task.set_completed(task_output)
            main_task.add_message(A2AMessageRole.AGENT, task_output)
            if not already_skipping:
                await self._update_task_record(main_task, completed=True)
                await collaboration_service.increment_usage(collab.id)
            yield {
                "type": "iteration_complete",
                "round": iteration_config.max_iterations,
                "passed": False,
            }
            yield {
                "type": "task_complete",
                "task_id": main_task.id,
                "status": "completed",
                "output": task_output,
                "messages": [m.dict() for m in main_task.messages],
            }

        except Exception as e:
            logger.error(f"Iteration failed: {e}", exc_info=True)
            main_task.set_failed(str(e))
            if not already_skipping:
                await self._update_task_record(main_task, completed=True)
            yield {"type": "task_failed", "task_id": main_task.id, "error": str(e)}
        finally:
            # Only reset flags if we created them (not if _run_in_background set them)
            if not already_skipping:
                self._skip_task_record = False
                self._shared_task_id = None

    # -------------------------------------------------------------------------
    # Feedback injection
    # -------------------------------------------------------------------------

    def _inject_feedback(
        self, input_text: str, context: Dict[str, Any], round_num: int
    ) -> str:
        """Build enhanced input by appending previous round feedback and artifacts.

        Round 1: return original input unchanged.
        Round 2+: prepend iteration context and feedback.
        """
        if round_num <= 1:
            return input_text

        parts = [
            f"【迭代上下文-第{round_num}轮】",
            f"原始任务：{context['original_input']}",
        ]

        # Summarize previous rounds
        for entry in context["history"]:
            parts.append(f"\n--- 第{entry['round']}轮回顾 ---")
            if entry.get("artifacts"):
                for a in entry["artifacts"]:
                    parts.append(f"[产物: {a['name']} ({a['type']})]\n{a['content'][:2000]}")
            parts.append(f"评估反馈：{entry['feedback']}")

        parts.append(f"\n请基于以上前几轮的结果和反馈进行改进，完成原始任务。")
        parts.append(f"\n当前任务：{input_text}")

        return "\n".join(parts)

    # -------------------------------------------------------------------------
    # Artifact extraction
    # -------------------------------------------------------------------------

    @staticmethod
    def _infer_artifact_type(name: str) -> ArtifactType:
        """Infer artifact type from its name."""
        name_lower = name.lower()
        code_keywords = ["代码", "code", "脚本", "script", "程序"]
        data_keywords = ["数据", "指标", "data", "metric", "绩效", "结果", "回测结果"]
        chart_keywords = ["图表", "chart", "图", "plot"]

        if any(kw in name_lower for kw in code_keywords):
            return ArtifactType.CODE
        if any(kw in name_lower for kw in data_keywords):
            return ArtifactType.DATA
        if any(kw in name_lower for kw in chart_keywords):
            return ArtifactType.CHART
        return ArtifactType.TEXT

    def _extract_artifacts_from_text(
        self,
        text: str,
        collaboration_id: str,
        task_id: str,
        round_num: int,
        producer_agent_id: str = "",
        producer_role: str = "",
    ) -> List[Artifact]:
        """Extract artifacts from agent output text using 【产物：xxx】 markers."""
        artifacts = []
        matches = _ARTIFACT_PATTERN.findall(text)

        for name, content in matches:
            name = name.strip()
            content = content.strip()
            if not content:
                continue

            artifact_type = self._infer_artifact_type(name)
            artifact = Artifact(
                id=str(uuid.uuid4()),
                collaboration_id=collaboration_id,
                task_id=task_id,
                round=round_num,
                producer_agent_id=producer_agent_id,
                producer_role=producer_role,
                name=name,
                artifact_type=artifact_type,
                content=content,
                metadata={},
                created_at=beijing_now(),
            )
            artifacts.append(artifact)

        return artifacts

    async def _extract_and_save_artifacts(
        self,
        task: A2ATask,
        collaboration_id: str,
        round_num: int,
    ) -> List[Artifact]:
        """Extract artifacts from all agent messages in a task and persist them."""
        all_artifacts: List[Artifact] = []

        for msg in task.messages:
            if msg.role != A2AMessageRole.AGENT:
                continue
            text = msg.get_text()
            if not text:
                continue

            artifacts = self._extract_artifacts_from_text(
                text=text,
                collaboration_id=collaboration_id,
                task_id=task.id,
                round_num=round_num,
            )
            all_artifacts.extend(artifacts)

        if all_artifacts:
            await self._save_artifacts(all_artifacts)

        return all_artifacts

    async def _save_artifacts(self, artifacts: List[Artifact]) -> None:
        """Persist artifacts to database."""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()
        try:
            for artifact in artifacts:
                await db.execute(
                    """
                    INSERT INTO collaboration_artifacts
                    (id, collaboration_id, task_id, round, producer_agent_id,
                     producer_role, name, artifact_type, content, metadata_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact.id,
                        artifact.collaboration_id,
                        artifact.task_id,
                        artifact.round,
                        artifact.producer_agent_id,
                        artifact.producer_role,
                        artifact.name,
                        artifact.artifact_type.value,
                        artifact.content,
                        json.dumps(artifact.metadata, ensure_ascii=False),
                        artifact.created_at.isoformat(),
                    ),
                )
            await db.commit()
        finally:
            await db.disconnect()

    # -------------------------------------------------------------------------
    # Evaluation
    # -------------------------------------------------------------------------

    async def _evaluate(
        self,
        output: str,
        iteration_config: IterationConfig,
        context: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Evaluate whether the iteration output passes.

        Returns (passed: bool, feedback: str).
        """
        # If evaluator agent configured, delegate to it
        if iteration_config.evaluator:
            return await self._evaluate_with_agent(output, iteration_config, context)

        # If evaluator_prompt configured, use LLM directly
        if iteration_config.evaluator_prompt:
            return await self._evaluate_with_llm(output, iteration_config, context)

        # No evaluator configured — always pass (safe degradation)
        logger.warning("No evaluator configured for iteration, auto-passing")
        return True, "未配置评估器，自动通过"

    async def _evaluate_with_agent(
        self,
        output: str,
        iteration_config: IterationConfig,
        context: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Evaluate using a dedicated evaluator agent."""
        from app.services.agent_registry import agent_registry

        evaluator = iteration_config.evaluator
        prompt = self._build_evaluation_prompt(output, iteration_config, context)

        agent_task = A2ATask(id=str(uuid.uuid4()), input=prompt)
        result = await agent_registry.call_agent(evaluator.agent_id, agent_task)

        return self._parse_evaluation_result(result.output or "")

    async def _evaluate_with_llm(
        self,
        output: str,
        iteration_config: IterationConfig,
        context: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Evaluate using LLM directly (no dedicated agent)."""
        prompt = self._build_evaluation_prompt(output, iteration_config, context)

        try:
            from app.services.llm_service import llm_service
            response = await llm_service.chat(prompt, use_tools=False)
            return self._parse_evaluation_result(response)
        except Exception as e:
            logger.error(f"LLM evaluation failed: {e}")
            return True, f"评估失败({str(e)})，自动通过"

    def _build_evaluation_prompt(
        self,
        output: str,
        iteration_config: IterationConfig,
        context: Dict[str, Any],
    ) -> str:
        """Build the evaluation prompt."""
        eval_instruction = iteration_config.evaluator_prompt or "请评估以下输出是否达标。"

        # Include previous round artifacts for context
        prev_context = ""
        if context.get("artifacts"):
            artifact_summaries = []
            for a in context["artifacts"]:
                artifact_summaries.append(
                    f"- [{a.name} ({a.artifact_type.value})]\n{a.content[:1000]}"
                )
            prev_context = "\n\n前几轮产出：\n" + "\n".join(artifact_summaries)

        return f"""{eval_instruction}

待评估内容：
{output}
{prev_context}

请先给出评估结论，然后说明原因。
如果达标，请在回复开头写：通过
如果不达标，请在回复开头写：未通过
然后给出具体的不达标原因和改进建议。"""

    @staticmethod
    def _parse_evaluation_result(response: str) -> Tuple[bool, str]:
        """Parse evaluation result from LLM/agent output.

        Returns (passed, feedback).
        """
        response_stripped = response.strip()

        # Check for explicit pass/fail markers
        if response_stripped.startswith("通过"):
            feedback = response_stripped[2:].strip().lstrip("，。,.").strip()
            return True, feedback or "评估通过"
        if response_stripped.startswith("未通过"):
            feedback = response_stripped[3:].strip().lstrip("，。,.").strip()
            return False, feedback or "未通过"

        # Fallback: search for markers anywhere in text
        if "通过" in response_stripped and "未通过" not in response_stripped:
            return True, response_stripped

        if "未通过" in response_stripped:
            return False, response_stripped

        # Ambiguous — lean towards passing to avoid infinite loops
        logger.warning(f"Ambiguous evaluation result, treating as pass: {response[:200]}")
        return True, response_stripped

    # -------------------------------------------------------------------------
    # Artifact format instruction for prompts
    # -------------------------------------------------------------------------

    @staticmethod
    def get_artifact_format_instruction() -> str:
        """Returns the instruction snippet to append to agent prompts
        when iteration is enabled, telling agents to mark their outputs."""
        return """
输出格式要求：请在输出中用以下标记明确标注你的每个产出，每个产出单独标记：

【产物：产出名称】
产出内容

例如：
【产物：策略思路】
策略描述...

【产物：回测代码】
```python
代码...
```

【产物：绩效指标】
指标数据...

重要：必须使用【产物：xxx】标记，否则你的产出无法被系统识别和管理。"""

    # -------------------------------------------------------------------------
    # Task record persistence
    # -------------------------------------------------------------------------

    async def _create_task_record(self, collab_id: str, task: A2ATask):
        """Create task record in database"""
        db = DatabaseConnection(settings.DATABASE_URL)
        await db.connect()
        try:
            now = beijing_now().isoformat()
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
            completed_at = beijing_now().isoformat() if completed else None
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

    def _create_task(self, input_text: str) -> A2ATask:
        """Helper to create a standard A2ATask with RUNNING status"""
        return A2ATask(
            id=str(uuid.uuid4()),
            input=input_text,
            status=A2ATaskStatus(state=A2ATaskStatusState.RUNNING)
        )

    async def _wait_for_human_input(
        self, task_id: str, agent_id: str, role: str,
        sandbox=None, prompt: str = "", timeout: int = 1800
    ) -> Dict[str, Any]:
        """Suspend execution and wait for human input via the API.

        Registers the task in the global pending store. The frontend
        calls POST /tasks/{id}/human-input which validates the move
        (via sandbox if present) and wakes this coroutine.

        Args:
            task_id: The collaboration task ID.
            agent_id: Human agent identifier (usually "human").
            role: The role of the human player (e.g. "participant_0").
            sandbox: Optional sandbox instance for move validation.
            prompt: State description shown to the human player.
            timeout: Maximum wait time in seconds (default 30 min).

        Returns:
            Result dict with at least ``success`` key.
        """
        from app.api.collaborations import _pending_human_inputs
        move_event = asyncio.Event()
        _pending_human_inputs[task_id] = {
            "event": move_event,
            "role": role,
            "agent_id": agent_id,
            "sandbox": sandbox,
            "result": None,
            "prompt": prompt,
        }
        try:
            await asyncio.wait_for(move_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            _pending_human_inputs.pop(task_id, None)
            return {"success": False, "error": "等待人类输入超时"}
        entry = _pending_human_inputs.pop(task_id, None)
        return entry["result"] if entry else {"success": False, "error": "输入已取消"}
