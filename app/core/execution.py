"""Tool execution engine with intelligent retry mechanism"""
import asyncio
import logging
import json
from typing import Dict, List, Any, Optional, AsyncGenerator, Callable
from dataclasses import dataclass, field
from enum import Enum
import uuid
from datetime import datetime

from app.services.mcp_pool import mcp_client_pool

logger = logging.getLogger(__name__)


class ComplexityLevel(str, Enum):
    """Task complexity level"""
    SIMPLE = "SIMPLE"
    MEDIUM = "MEDIUM"
    COMPLEX = "COMPLEX"


class ExecutionStrategy(str, Enum):
    """Execution strategy"""
    SINGLE = "single"
    CHAIN = "chain"
    PARALLEL = "parallel"
    MIXED = "mixed"
    THINKING = "thinking"  # 纯思考任务，不需要工具调用


@dataclass
class ExecutionStep:
    """Single execution step"""
    step_id: str
    tool_name: str
    arguments: Dict[str, Any]
    depends_on: List[str] = field(default_factory=list)
    parallel: bool = False
    retry_on_failure: bool = True
    max_retries: int = 3
    retry_count: int = 0
    status: str = "pending"  # pending, running, completed, failed
    result: Optional[Any] = None
    error: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


@dataclass
class ExecutionPlan:
    """Tool execution plan"""
    plan_id: str
    complexity: ComplexityLevel
    strategy: ExecutionStrategy
    description: str
    steps: List[ExecutionStep]
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def total_steps(self) -> int:
        """Get total number of steps"""
        return len(self.steps)


class ErrorType(str, Enum):
    """Error type for retry strategy"""
    NETWORK = "network"
    TIMEOUT = "timeout"
    PARAMETER = "parameter"
    TOOL_NOT_FOUND = "tool_not_found"
    PERMISSION = "permission"
    UNKNOWN = "unknown"


@dataclass
class ExecutionState:
    """Execution state tracking"""
    plan_id: str
    total_steps: int
    completed_steps: int = 0
    failed_steps: int = 0
    current_step: Optional[str] = None
    results: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)


class ToolExecutionEngine:
    """Tool execution engine with intelligent retry"""

    def __init__(self):
        """Initialize execution engine"""
        self.current_execution: Optional[ExecutionState] = None
        self.execution_callbacks: List[Callable] = []
        self._event_queue = []

    def register_callback(self, callback: Callable):
        """Register callback for execution events

        Args:
            callback: Callback function
        """
        self.execution_callbacks.append(callback)

    async def execute_plan(
        self,
        plan: ExecutionPlan,
        context: Optional[Dict[str, Any]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Execute execution plan with streaming status

        Args:
            plan: Execution plan to execute
            context: Initial context

        Yields:
            Execution status updates
        """
        self.current_execution = ExecutionState(
            plan_id=plan.plan_id,
            total_steps=len(plan.steps),
            context=context or {}
        )

        # Create event queue for streaming
        self._event_queue = asyncio.Queue()

        # Notify all events through queue
        async def event_collector(event):
            self._event_queue.put_nowait(event)

        # Register temporary event collector
        self.execution_callbacks.append(event_collector)

        # Notify start (only for non-thinking strategies to avoid duplicate display)
        if plan.strategy != ExecutionStrategy.THINKING:
            await self._emit({
                "type": "execution_start",
                "plan_id": plan.plan_id,
                "total_steps": plan.total_steps,
                "complexity": plan.complexity.value,
                "strategy": plan.strategy.value,
                "description": plan.description
            })

        # Notify thinking (only for non-thinking strategies)
        if plan.strategy != ExecutionStrategy.THINKING:
            await self._emit({
                "type": "thinking",
                "message": f"分析任务复杂度: {plan.complexity.value}"
            })

            await self._emit({
                "type": "thinking",
                "message": f"使用策略: {plan.strategy.value}"
            })

        # Execute based on strategy in a separate task
        async def execute_strategy():
            if plan.strategy == ExecutionStrategy.SINGLE:
                return await self._execute_single(plan)
            elif plan.strategy == ExecutionStrategy.CHAIN:
                return await self._execute_chain(plan)
            elif plan.strategy == ExecutionStrategy.PARALLEL:
                return await self._execute_parallel(plan)
            elif plan.strategy == ExecutionStrategy.MIXED:
                return await self._execute_mixed(plan)
            elif plan.strategy == ExecutionStrategy.THINKING:
                return await self._execute_thinking(plan)
            else:
                raise ValueError(f"Unknown strategy: {plan.strategy}")

    async def _execute_thinking(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """Execute thinking strategy - complete deep thinking with streaming

        Args:
            plan: Execution plan

        Returns:
            Aggregated results
        """
        results = {}

        try:
            # Send thinking start event
            await self._emit({
                "type": "thinking_start",
                "task": plan.description
            })

            # Create comprehensive thinking prompt
            thinking_prompt = f"""【开始深度思考】用户请求: {plan.description}

请为这个任务进行深度思考和规划。你的思考过程将实时展示给用户。

要求：
1. 展示完整的思考过程，包括：
   - 理解了用户需求和约束条件
   - 分析了关键因素和可能的解决方案
   - 权衡了不同选项的利弊
   - 制定了具体的行动方案

2. 在思考过程中，明确标记关键的分析阶段：
   - 【阶段1】需求分析
   - 【阶段2】方案设计
   - 【阶段3】详细规划

3. 最终输出完整的规划结果，包括：
   - 明确的执行步骤
   - 具体的建议和注意事项
   - 结构化的方案展示

【思考完成】后，请按以下格式输出规划：

步骤1：[具体内容]
步骤2：[具体内容]
步骤3：[具体内容]

请开始你的深度思考过程...
"""

            # Get LLM client
            from app.services.llm_service import llm_service

            # Prepare messages
            messages = [{"role": "user", "content": thinking_prompt}]

            # Stream thinking process
            thinking_content = ""
            async for chunk in llm_service.chat_stream(messages):
                thinking_content += chunk

                # Send thinking chunk event
                await self._emit({
                    "type": "thinking_chunk",
                    "content": chunk
                })

            # Send thinking complete event
            await self._emit({
                "type": "thinking_complete",
                "content": thinking_content
            })

            # Update all steps as completed (virtual)
            for step in plan.steps:
                step.status = "completed"
                step.end_time = datetime.utcnow()
                self.current_execution.completed_steps += 1
                results[step.step_id] = {
                    "type": "thinking_step",
                    "description": step.tool_name,
                    "content": thinking_content,
                    "status": "completed"
                }

        except Exception as e:
            logger.error(f"Error in thinking execution: {e}")

            # Send error event
            await self._emit({
                "type": "thinking_error",
                "error": str(e)
            })

            # Update all steps as failed
            for step in plan.steps:
                step.status = "failed"
                step.error = str(e)
                self.current_execution.failed_steps += 1
                results[step.step_id] = {
                    "type": "thinking_step",
                    "description": step.tool_name,
                    "error": str(e),
                    "status": "failed"
                }

        return results

    async def _execute_single(self, plan: ExecutionPlan) -> Any:
        """Execute single step

        Args:
            plan: Execution plan

        Returns:
            Execution result
        """
        if len(plan.steps) == 0:
            return {}

        step = plan.steps[0]

        # Use the execution state already initialized in execute_plan
        # Don't create a new state here to avoid losing the original state

        result = await self._execute_step(step)

        return result

    async def _execute_chain(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """Execute steps in chain

        Args:
            plan: Execution plan

        Returns:
            Aggregated results
        """
        results = {}

        for step in plan.steps:
            # Check dependencies
            if not await self._check_dependencies(step):
                logger.warning(f"Step {step.step_id} dependencies not met, skipping")
                continue

            result = await self._execute_step(step)

            if step.status == "completed":
                results[step.step_id] = result
                # Add to context for next steps
                self.current_execution.context[step.step_id] = result
            elif step.status == "failed":
                # Check if step is critical
                if step.retry_on_failure and step.retry_count >= step.max_retries:
                    logger.error(f"Step {step.step_id} failed after max retries")
                    if self.current_execution is not None:
                        self.current_execution.failed_steps += 1
                    # Continue to next step if not critical
                    continue

        return results

    async def _execute_parallel(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """Execute steps in parallel

        Args:
            plan: Execution plan

        Returns:
            Aggregated results
        """
        # Group steps that can run in parallel
        parallel_groups = self._group_parallel_steps(plan.steps)

        results = {}

        for group in parallel_groups:
            # Execute group in parallel
            tasks = [self._execute_step(step) for step in group]
            group_results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(group_results):
                if not isinstance(result, Exception):
                    results[group[i].step_id] = result
                    self.current_execution.context[group[i].step_id] = result

        return results

    async def _execute_mixed(self, plan: ExecutionPlan) -> Dict[str, Any]:
        """Execute mixed strategy (parallel + chain)

        Args:
            plan: Execution plan

        Returns:
            Aggregated results
        """
        results = {}

        for step in plan.steps:
            # Check dependencies
            if not await self._check_dependencies(step):
                # Wait for dependencies
                await asyncio.sleep(0.1)
                continue

            if step.parallel:
                # Execute in parallel with other parallel steps
                pass  # Simplified for now
            else:
                # Execute sequentially
                result = await self._execute_step(step)

                if step.status == "completed":
                    results[step.step_id] = result
                    self.current_execution.context[step.step_id] = result

        return results

    async def _execute_step(self, step: ExecutionStep) -> Any:
        """Execute a single step with retry

        Args:
            step: Execution step

        Returns:
            Execution result
        """
        step.status = "running"
        step.start_time = datetime.utcnow()

        # Handle case when called directly without execute_plan (current_execution is None)
        if self.current_execution is not None:
            step_number = self.current_execution.completed_steps + 1
            total_steps = self.current_execution.total_steps
        else:
            step_number = 1
            total_steps = 1

        await self._emit({
            "type": "step_start",
            "step_id": step.step_id,
            "step_number": step_number,
            "total_steps": total_steps,
            "tool_name": step.tool_name,
            "arguments": step.arguments
        })

        while step.retry_count <= step.max_retries:
            try:
                await self._emit({
                    "type": "step_progress",
                    "step_id": step.step_id,
                    "message": f"执行工具 {step.tool_name}..."
                })

                # Execute tool via unified tool manager
                from app.core.tool_manager import get_tool_manager
                tool_manager = get_tool_manager()
                result = await tool_manager.call_tool(
                    step.tool_name,
                    step.arguments
                )

                step.status = "completed"
                step.result = result
                step.end_time = datetime.utcnow()
                if self.current_execution is not None:
                    self.current_execution.completed_steps += 1

                await self._emit({
                    "type": "step_complete",
                    "step_id": step.step_id,
                    "success": True,
                    "result": self._truncate_result(result),
                    "result_preview": self._get_result_preview(result)
                })

                return result

            except Exception as e:
                error_type = self._classify_error(e)
                step.error = str(e)
                step.retry_count += 1
                logger.error(f"Error executing tool '{step.tool_name}': {e}, retry {step.retry_count}/{step.max_retries}")

                await self._emit({
                    "type": "step_error",
                    "step_id": step.step_id,
                    "error": str(e),
                    "error_type": error_type.value,
                    "retry_count": step.retry_count,
                    "max_retries": step.max_retries
                })

                # Apply retry strategy
                if step.retry_count < step.max_retries:
                    retry_delay = self._get_retry_delay(error_type, step.retry_count)
                    logger.info(f"Retrying {step.tool_name} in {retry_delay}s...")
                    await asyncio.sleep(retry_delay)

                    # Try alternative approach based on error type
                    if error_type == ErrorType.PARAMETER:
                        # Let LLM regenerate parameters (not implemented yet)
                        pass
                    elif error_type == ErrorType.TOOL_NOT_FOUND:
                        # Try alternative tool (not implemented yet)
                        pass
                else:
                    # Max retries reached
                    step.status = "failed"
                    step.end_time = datetime.utcnow()
                    if self.current_execution is not None:
                        self.current_execution.failed_steps += 1
                    break

        return step.result

    async def _check_dependencies(self, step: ExecutionStep) -> bool:
        """Check if step dependencies are satisfied

        Args:
            step: Execution step

        Returns:
            True if dependencies satisfied
        """
        if self.current_execution is None:
            # Called directly without execute_plan, skip dependency check
            return True
        for dep_id in step.depends_on:
            if dep_id not in self.current_execution.context:
                return False
        return True

    def _group_parallel_steps(self, steps: List[ExecutionStep]) -> List[List[ExecutionStep]]:
        """Group steps that can run in parallel

        Args:
            steps: List of execution steps

        Returns:
            Groups of parallel steps
        """
        groups = []
        current_group = []
        executed_step_ids = set()

        for step in steps:
            # Check if dependencies are met
            deps_satisfied = all(
                dep_id in executed_step_ids
                for dep_id in step.depends_on
            )

            if deps_satisfied:
                current_group.append(step)
                executed_step_ids.add(step.step_id)

            if len(current_group) == 4 or step == steps[-1]:
                groups.append(current_group)
                current_group = []

        return groups

    def _classify_error(self, error: Exception) -> ErrorType:
        """Classify error type for retry strategy

        Args:
            error: Exception

        Returns:
            Error type
        """
        error_msg = str(error).lower()

        if "network" in error_msg or "connection" in error_msg:
            return ErrorType.NETWORK
        elif "timeout" in error_msg:
            return ErrorType.TIMEOUT
        elif "parameter" in error_msg or "argument" in error_msg:
            return ErrorType.PARAMETER
        elif "not found" in error_msg or "tool" in error_msg:
            return ErrorType.TOOL_NOT_FOUND
        elif "permission" in error_msg or "denied" in error_msg:
            return ErrorType.PERMISSION
        else:
            return ErrorType.UNKNOWN

    def _get_retry_delay(self, error_type: ErrorType, retry_count: int) -> float:
        """Get retry delay based on error type

        Args:
            error_type: Error type
            retry_count: Current retry count

        Returns:
            Delay in seconds
        """
        if error_type == ErrorType.NETWORK:
            # Exponential backoff
            return min(2 ** retry_count, 10)
        elif error_type == ErrorType.TIMEOUT:
            # Immediate retry
            return 0.1
        elif error_type in [ErrorType.PARAMETER, ErrorType.TOOL_NOT_FOUND]:
            # No delay, need quick response
            return 0
        else:
            # Fixed delay for unknown errors
            return 2.0

    def _get_result_preview(self, result: Any) -> str:
        """Get result preview for display

        Args:
            result: Result

        Returns:
            Preview string
        """
        if result is None:
            return "None"
        elif isinstance(result, (str, int, float, bool)):
            return str(result)[:200]
        elif isinstance(result, (dict, list)):
            result_str = json.dumps(result, ensure_ascii=False)
            return result_str[:200] + "..."
        else:
            return str(result)[:200]

    def _truncate_result(self, result: Any) -> Any:
        """Truncate large results

        Args:
            result: Result

        Returns:
            Truncated result
        """
        if isinstance(result, str) and len(result) > 10000:
            return result[:10000] + "... (truncated)"
        elif isinstance(result, list) and len(result) > 100:
            return result[:100]
        elif isinstance(result, dict):
            return {k: self._truncate_result(v) for k, v in list(result.items())[:20]}
        return result

    async def _emit(self, event: Dict[str, Any]):
        """Emit execution event

        Args:
            event: Event data
        """
        for callback in self.execution_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                logger.error(f"Error in callback: {e}")

        # Store event in queue for yielding
        if hasattr(self, '_event_queue') and self._event_queue:
            try:
                self._event_queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Queue full, drop event


# Global execution engine instance
execution_engine = ToolExecutionEngine()
