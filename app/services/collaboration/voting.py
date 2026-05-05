"""Voting/Ensemble collaboration mode - multiple agents vote, aggregator consolidates"""
import asyncio
import logging
import uuid
from collections import Counter
from typing import List, Dict, Any

from app.models.a2a import A2ATask, A2AMessageRole
from app.models.collaboration import CollaborationResponse
from app.services.collaboration.base import BaseCollaborationMode
from app.services.collaboration_service import collaboration_service
from app.services.agent_registry import agent_registry

logger = logging.getLogger(__name__)


class VotingCollaboration(BaseCollaborationMode):
    """Voting/Ensemble mode: multiple agents independently answer the same question,
    then an aggregator consolidates the results via majority vote.
    """

    def _build_voter_prompt(self, input_text: str, custom_instruction: str = None) -> str:
        """Build the prompt for a voter agent."""
        prefix = f"{custom_instruction}\n\n" if custom_instruction else ""
        return f"""{prefix}你是一个独立的投票者。请对以下问题表达你的观点并做出明确选择，不要反问或请他人决定。

{input_text}

要求：
1. 你必须明确表明自己的立场或选择
2. 给出你的理由
3. 不要复述问题或让其他人来选——你就是投票者，由你来做决定"""

    async def _aggregate_with_agent(self, aggregator, input_text, votes, config):
        """Use an aggregator agent to produce final answer."""
        custom_instruction = config.get("aggregator_prompt")
        votes_text = "\n".join(
            f"Agent {voter.agent_id} (优先级: {voter.priority}): {answer}"
            for voter, answer in votes
        )

        prefix = f"{custom_instruction}\n\n" if custom_instruction else ""
        prompt = f"""{prefix}你是答案聚合器。多个独立Agent对同一个问题给出了各自的回答。

原始问题：{input_text}

各Agent的回答：
{votes_text}

请根据以上回答，综合分析并给出最终的、最准确的答案。如果多数Agent意见一致，采用多数意见；如果意见分歧，请分析各方理由并给出最佳判断。

请直接输出最终答案。"""

        agg_task = A2ATask(id=str(uuid.uuid4()), input=prompt)
        result = await agent_registry.call_agent(aggregator.agent_id, agg_task)
        return result.output or "No aggregated output"

    @staticmethod
    def _aggregate_simple(votes, strategy):
        """Simple aggregation without an aggregator agent (majority vote)"""
        answers = [answer for _, answer in votes if not answer.startswith("[Failed")]

        if not answers:
            return "All voters failed"

        counter = Counter(answers)
        most_common = counter.most_common(1)
        return most_common[0][0] if most_common else answers[0]

    async def execute(self, collab: CollaborationResponse, input_text: str) -> A2ATask:
        task = self._create_task(input_text)
        await self._create_task_record(collab.id, task)

        try:
            voters = [a for a in collab.agents if a.role == "voter"]
            aggregator = next((a for a in collab.agents if a.role == "aggregator"), None)

            if not voters:
                raise ValueError("No voter agents found in voting collaboration")

            config = collab.config_json
            strategy = config.get("strategy", "majority")

            # Step 1: All voters answer independently in parallel
            voter_instruction = config.get("voter_prompt_template")
            tasks = []
            for voter in voters:
                voter_input = self._build_voter_prompt(input_text, voter_instruction)
                t = A2ATask(id=str(uuid.uuid4()), input=voter_input)
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
        task = self._create_task(input_text)
        await self._create_task_record(collab.id, task)

        try:
            yield {"type": "task_start", "task_id": task.id, "input": input_text, "mode": "voting"}

            voters = [a for a in collab.agents if a.role == "voter"]
            aggregator = next((a for a in collab.agents if a.role == "aggregator"), None)

            if not voters:
                yield {"type": "task_failed", "error": "No voter agents found"}
                return

            config = collab.config_json
            strategy = config.get("strategy", "majority")
            voter_instruction = config.get("voter_prompt_template")

            # Step 1: All voters answer in parallel
            for voter in voters:
                yield {
                    "type": "agent_start",
                    "agent_id": voter.agent_id,
                    "role": "voter",
                    "round": 1
                }

            voter_input = self._build_voter_prompt(input_text, voter_instruction)
            tasks = [(v, A2ATask(id=str(uuid.uuid4()), input=voter_input)) for v in voters]
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
