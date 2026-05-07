"""Chat API endpoints"""
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from typing import List, Optional, Dict, Any
import json
import logging
from datetime import datetime
from app.utils.timezone import beijing_now

from app.models.chat import ChatRequest, ChatResponse, StreamMessage, MessageCreate, MessageRole
from app.database.repositories import MessageRepository, SessionRepository
from app.services.llm_service import LLMService
from app.services.session_working_memory import SessionWorkingMemory
from app.services.planning_chat_service import planning_chat_service
from app.core.strategy_router import strategy_router

logger = logging.getLogger(__name__)


class PendingResponseTracker:
    """追踪正在后台生成的回复，用于断连后继续处理及重连时通知"""

    def __init__(self):
        self._pending: Dict[str, dict] = {}  # session_id -> info
        self._completion_events: Dict[str, asyncio.Event] = {}
        self._generation: Dict[str, int] = {}

    def mark_pending(self, session_id: str, user_message: str, agent_id: Optional[str] = None):
        gen = self._generation.get(session_id, 0) + 1
        self._generation[session_id] = gen

        # 如果有旧的 watcher 在等，先唤醒它让它退出
        old_event = self._completion_events.get(session_id)
        if old_event and not old_event.is_set():
            old_event.set()

        self._pending[session_id] = {
            "status": "generating",
            "started_at": beijing_now().isoformat(),
            "user_message": user_message,
            "agent_id": agent_id,
            "generation": gen,
        }
        self._completion_events[session_id] = asyncio.Event()

    def mark_completed(self, session_id: str):
        self._pending.pop(session_id, None)
        event = self._completion_events.pop(session_id, None)
        if event and not event.is_set():
            event.set()

    def is_pending(self, session_id: str) -> bool:
        return session_id in self._pending

    def get_pending(self, session_id: str) -> Optional[dict]:
        return self._pending.get(session_id)

    def get_completion_event(self, session_id: str) -> Optional[asyncio.Event]:
        return self._completion_events.get(session_id)

    def get_generation(self, session_id: str) -> int:
        return self._generation.get(session_id, 0)


# 全局实例
pending_tracker = PendingResponseTracker()


async def _inject_memory_into_agent_config(
    agent_config_dict: dict,
    agent_id: str,
    user_message: str
) -> dict:
    """将 agent 长期记忆注入到 agent_config 的 system_prompt 中

    只有当 agent 启用了长期记忆时才注入。

    Args:
        agent_config_dict: Agent 配置字典
        agent_id: Agent ID
        user_message: 当前用户消息（用于语义召回）

    Returns:
        更新后的 agent_config_dict
    """
    try:
        from app.services.agent_memory_service import agent_memory_service

        # 获取记忆画像
        profile = await agent_memory_service.get_agent_profile(agent_id)
        profile_text = profile.to_prompt_text()

        # 语义召回相关记忆
        recalled = await agent_memory_service.recall(agent_id, user_message, n=5)
        recalled_texts = [f"- [{r.memory_type.value}] {r.content}" for r in recalled]

        # 注入到 system_prompt
        base_prompt = agent_config_dict.get("system_prompt", "")
        memory_sections = []

        if profile_text:
            memory_sections.append(profile_text)

        if recalled_texts:
            memory_sections.append(
                "与当前话题相关的历史记忆：\n" + "\n".join(recalled_texts)
            )

        if memory_sections:
            memory_block = "\n\n【记忆上下文】\n" + "\n\n".join(memory_sections)
            agent_config_dict["system_prompt"] = base_prompt + memory_block
            logger.info(f"Injected memory context for agent {agent_id}: profile={bool(profile_text)}, recalled={len(recalled_texts)}")

    except Exception as e:
        logger.warning(f"Failed to inject memory for agent {agent_id}: {e}")

    return agent_config_dict


async def _extract_memories_on_session_end(
    agent_id: str,
    session_id: str,
    memory_service: SessionWorkingMemory
):
    """对话结束时提取记忆（异步，不阻塞响应）

    Args:
        agent_id: Agent ID
        session_id: Session ID
        memory_service: SessionWorkingMemory 实例
    """
    try:
        from app.services.agent_memory_service import agent_memory_service

        # 获取完整对话消息
        all_messages = memory_service.get_all_messages(session_id)
        if all_messages:
            count = await agent_memory_service.extract_and_store(
                agent_id=agent_id,
                session_id=session_id,
                conversation_messages=all_messages
            )
            logger.info(f"Extracted {count} memories from session {session_id} for agent {agent_id}")
    except Exception as e:
        logger.error(f"Error extracting memories on session end: {e}", exc_info=True)

async def _run_llm_and_save(
    session_id: str,
    message: str,
    history: list,
    agent_config_dict: Optional[dict],
    execution_mode: str,
    deep_thinking: bool,
    agent_id: Optional[str],
    memory_service: SessionWorkingMemory,
    message_repo: MessageRepository,
    websocket: Optional[WebSocket] = None,
) -> str:
    """执行 LLM 调用并保存结果。

    WebSocket 断连后会继续处理：send 失败时标记断连，后续只积累不发送，
    LLM 完成后无论如何都将回答保存到数据库和工作记忆。

    Args:
        websocket: 可选的 WebSocket 连接，断连后本函数内部自动感知

    Returns:
        full_response: 完整的 AI 回答文本
    """
    ws_connected = websocket is not None
    full_response = ""
    sent_end = False

    async def _send_event(event: dict):
        """安全发送事件，断连后静默跳过"""
        nonlocal ws_connected
        if not ws_connected:
            return
        try:
            await websocket.send_json(event)
        except Exception:
            ws_connected = False
            logger.info(f"WebSocket disconnected during LLM processing for session {session_id}, continuing in background")

    # ── Direct mode ──
    if execution_mode == "direct":
        logger.info(f"Starting strategy_router.execute() for message: {message[:50]}...")
        try:
            gen = strategy_router.execute(
                message,
                agent_config=agent_config_dict,
                conversation_history=history,
                deep_thinking=deep_thinking,
            )
            async for event in gen:
                await _send_event(event)
                if event.get("type") == "message":
                    full_response += event.get("content", "")
                if event.get("type") == "end":
                    sent_end = True
        except Exception as e:
            logger.error(f"Error in strategy_router.execute() loop: {e}", exc_info=True)
            await _send_event({"type": "error", "message": f"Execution error: {str(e)}"})
        finally:
            if not sent_end:
                await _send_event({"type": "end"})

    # ── React mode ──
    elif execution_mode == "react":
        from app.core.react_cot_executor import ReActCotExecutor

        if agent_config_dict:
            agent_config_dict["thinking_effort"] = agent_config_dict.get("thinking_effort", "medium")
            agent_config_dict["max_react_steps"] = agent_config_dict.get("max_react_steps", 15)

        executor = ReActCotExecutor(agent_config=agent_config_dict)
        try:
            async for event in executor.execute(
                message,
                conversation_history=history,
                deep_thinking=True,
            ):
                await _send_event(event)
                if event.get("type") == "cot_complete":
                    full_response = event.get("message", "") or full_response
                if event.get("type") == "end":
                    sent_end = True
        except Exception as e:
            logger.error(f"ReAct execution error: {e}", exc_info=True)
            await _send_event({"type": "error", "content": f"执行错误: {str(e)}"})
        finally:
            if not sent_end:
                await _send_event({"type": "end"})

    # ── Plan mode ──
    else:
        try:
            async for event in planning_chat_service.chat(
                message,
                conversation_history=history,
                enable_planning=True,
                use_react=False,
                agent_config=agent_config_dict,
                deep_thinking=True,
            ):
                await _send_event(event)
                if event.get("type") == "message":
                    full_response += event.get("content", "")
        except Exception as e:
            logger.error(f"Plan mode execution error: {e}", exc_info=True)
            await _send_event({"type": "error", "content": f"执行错误: {str(e)}"})

    # ── 无论 WebSocket 状态如何，保存结果 ──
    if full_response:
        try:
            await message_repo.create(MessageCreate(
                session_id=session_id,
                content=full_response,
                role=MessageRole.ASSISTANT,
            ))
            await _add_assistant_message(
                memory_service, session_id, full_response,
                agent_model=agent_config_dict.get("model") if agent_config_dict else None,
            )
            logger.info(f"Saved assistant response for session {session_id} (ws_connected={ws_connected})")
        except Exception as e:
            logger.error(f"Failed to save assistant response for session {session_id}: {e}", exc_info=True)
    else:
        logger.warning(f"No full_response generated for session {session_id}")

    return full_response


router = APIRouter(prefix="/api/chat", tags=["chat"])


async def _add_assistant_message(
    memory_service: SessionWorkingMemory,
    session_id: str,
    content: str,
    agent_model: Optional[str] = None
):
    """添加助手消息到工作记忆，并检查是否需要摘要"""
    memory_service.add_message(session_id, MessageRole.ASSISTANT, content)
    await memory_service.maybe_summarize(session_id, agent_model=agent_model)


# Dependency functions
def get_session_repo():
    from app.main import session_repo
    return session_repo


def get_message_repo():
    from app.main import message_repo
    return message_repo


def get_llm_service():
    from app.main import llm_service
    return llm_service


def get_memory_service():
    from app.main import memory_service
    return memory_service


async def get_dependencies(
    session_repo: SessionRepository = Depends(get_session_repo),
    message_repo: MessageRepository = Depends(get_message_repo),
    llm_service: LLMService = Depends(get_llm_service),
    memory_service: SessionWorkingMemory = Depends(get_memory_service)
):
    """Dependency injection for chat endpoints"""
    return {
        "session_repo": session_repo,
        "message_repo": message_repo,
        "llm_service": llm_service,
        "memory_service": memory_service
    }


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    deps: dict = Depends(get_dependencies)
):
    """Send a chat message and get a response"""
    session_repo = deps["session_repo"]
    message_repo = deps["message_repo"]
    llm_service = deps["llm_service"]
    memory_service = deps["memory_service"]

    # Check if session exists
    session = await session_repo.get(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Save user message
    await message_repo.create(MessageCreate(
        session_id=request.session_id,
        content=request.message,
        role=MessageRole.USER
    ))

    # Add to memory
    memory_service.add_message(request.session_id, MessageRole.USER, request.message)

    # Get conversation history
    history = memory_service.get_conversation_history(request.session_id)

    try:
        # Call LLM
        response_text = await llm_service.chat(request.message, history)

        # Save assistant message
        await message_repo.create(MessageCreate(
            session_id=request.session_id,
            content=response_text,
            role=MessageRole.ASSISTANT
        ))

        # Add to memory
        await _add_assistant_message(memory_service, request.session_id, response_text)

        return ChatResponse(
            response=response_text,
            message_id=str(id(response_text)),
            session_id=request.session_id
        )

    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/stream")
async def chat_stream(
    websocket: WebSocket,
    session_repo: SessionRepository = Depends(get_session_repo),
    message_repo: MessageRepository = Depends(get_message_repo),
    llm_service: LLMService = Depends(get_llm_service),
    memory_service: SessionWorkingMemory = Depends(get_memory_service)
):
    """WebSocket endpoint for streaming chat"""
    await websocket.accept()

    session_id = None
    agent_id = None

    try:
        # Wait for initial message with session_id
        data = await websocket.receive_json()
        session_id = data.get("session_id")
        agent_id = data.get("agent_id")  # Optional: specific agent to use
        enable_planning = data.get("enable_planning", True)  # Enable planning by default
        deep_thinking = data.get("deep_thinking", False)  # Enable deep thinking mode

        if not session_id:
            await websocket.send_json({
                "type": "error",
                "content": "session_id is required"
            })
            await websocket.close()
            return

        # Check if session exists
        session = await session_repo.get(session_id)
        if not session:
            await websocket.send_json({
                "type": "error",
                "content": "Session not found"
            })
            await websocket.close()
            return

        # Load agent if specified
        agent = None
        if agent_id:
            from app.services.agent_service import agent_service
            agent = await agent_service.get(agent_id)

            if not agent:
                await websocket.send_json({
                    "type": "error",
                    "content": f"Agent {agent_id} not found"
                })

        # Load conversation history into memory (most recent 20 rounds = 40 messages)
        HISTORY_LIMIT = 40
        db_messages = await session_repo.get_history(session_id, limit=HISTORY_LIMIT)
        history_dicts = [{
            "role": msg.role.value,
            "content": msg.content
        } for msg in db_messages]
        memory_service.load_from_db(session_id, history_dicts)

        # Check total message count for "has_more" indicator
        total_messages = await session_repo.count_messages(session_id)

        # Send connection established message
        connection_message = {
            "type": "connected",
            "session_id": session_id
        }

        if agent:
            connection_message["agent"] = {
                "id": agent.id,
                "name": agent.name,
                "type": agent.type.value,
                "execution_mode": getattr(agent, "execution_mode", "plan")
            }

        await websocket.send_json(connection_message)

        # Send history messages to frontend if any
        if db_messages:
            history_message = {
                "type": "history",
                "messages": [{
                    "id": str(msg.id),
                    "role": msg.role.value,
                    "content": msg.content,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None
                } for msg in db_messages],
                "total": total_messages,
                "has_more": total_messages > HISTORY_LIMIT
            }
            await websocket.send_json(history_message)

        # Notify frontend if there's a pending response being generated in the background
        pending = pending_tracker.get_pending(session_id)
        if pending:
            await websocket.send_json({
                "type": "pending_response",
                "status": pending["status"],
                "user_message": pending["user_message"],
            })

            # 启动后台 watcher，等待后台生成完成后通知前端
            async def _watch_pending_response():
                gen = pending["generation"]
                event = pending_tracker.get_completion_event(session_id)
                if not event:
                    return
                try:
                    await asyncio.wait_for(event.wait(), timeout=300)
                except asyncio.TimeoutError:
                    logger.warning(f"Pending response watch timed out for session {session_id}")
                    return
                except Exception:
                    return

                # 检查 generation 是否匹配（如果用户已发新消息，由新 watcher 处理）
                if pending_tracker.get_generation(session_id) != gen:
                    return

                # 从 DB 获取已保存的助手回复
                try:
                    db_msgs = await session_repo.get_history(session_id, limit=5)
                    for msg in reversed(db_msgs):
                        if msg.role.value == "assistant":
                            await websocket.send_json({
                                "type": "response_completed",
                                "message": {
                                    "id": str(msg.id),
                                    "role": msg.role.value,
                                    "content": msg.content,
                                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                                }
                            })
                            return
                except Exception as e:
                    logger.warning(f"Failed to send response_completed: {e}")

            asyncio.create_task(_watch_pending_response())

        # Handle chat messages
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")
            new_agent_id = data.get("agent_id")
            action = data.get("action")
            # Update deep_thinking mode if provided in message
            current_deep_thinking = data.get("deep_thinking", deep_thinking)

            # Handle load_more_history action
            if action == "load_more_history":
                before_count = data.get("before", HISTORY_LIMIT)
                older_messages = await session_repo.get_older_messages(session_id, before_count, HISTORY_LIMIT)
                if older_messages:
                    await websocket.send_json({
                        "type": "more_history",
                        "messages": [{
                            "id": str(msg.id),
                            "role": msg.role.value,
                            "content": msg.content,
                            "created_at": msg.created_at.isoformat() if msg.created_at else None
                        } for msg in older_messages],
                        "has_more": len(older_messages) >= HISTORY_LIMIT
                    })
                else:
                    await websocket.send_json({
                        "type": "more_history",
                        "messages": [],
                        "has_more": False
                    })
                continue

            logger.info(f"Received message: {message[:50]}..., deep_thinking={current_deep_thinking}")

            # Check if agent_id is being updated
            if new_agent_id and new_agent_id != agent_id:
                logger.info(f"Switching agent from {agent_id} to {new_agent_id}")
                agent_id = new_agent_id

                # Load new agent
                agent = None
                if agent_id:
                    from app.services.agent_service import agent_service
                    agent = await agent_service.get(agent_id)

                    if not agent:
                        await websocket.send_json({
                            "type": "error",
                            "content": f"Agent {agent_id} not found"
                        })
                    else:
                        # Send confirmation
                        await websocket.send_json({
                            "type": "agent_switched",
                            "agent": {
                                "id": agent.id,
                                "name": agent.name,
                                "type": agent.type.value,
                                "execution_mode": getattr(agent, "execution_mode", "plan")
                            }
                        })

            if not message:
                continue

            # Save user message
            await message_repo.create(MessageCreate(
                session_id=session_id,
                content=message,
                role=MessageRole.USER
            ))

            # Add to memory
            memory_service.add_message(session_id, MessageRole.USER, message)

            # Get conversation history
            history = memory_service.get_conversation_history(session_id)

            try:
                # Convert agent config to dict if needed
                agent_config_dict = None
                if agent:
                    # First ensure agent skills are synced to registry
                    if hasattr(agent, "skills") and agent.skills:
                        from app.services.agent_service import agent_service
                        await agent_service._sync_agent_skills_to_registry(agent.id, agent.skills)

                    # Get skill system prompt addition
                    skill_system_prompt = ""
                    if hasattr(agent, "skills") and agent.skills:
                        from app.skills.registry import get_skill_registry
                        registry = get_skill_registry()
                        skill_system_prompt = registry.get_system_prompt_addition(agent.id)
                        if skill_system_prompt:
                            logger.info(f"Added skill system prompt for agent {agent.id}: {skill_system_prompt[:200]}...")

                    # Combine base system prompt with skill prompt
                    full_system_prompt = agent.system_prompt
                    if skill_system_prompt:
                        full_system_prompt = agent.system_prompt + "\n" + skill_system_prompt if agent.system_prompt else skill_system_prompt

                    # Inject current time at the beginning of system prompt for visibility
                    current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
                    time_prompt = f"【重要】当前日期时间：{current_time}。请基于此时间回答问题，不要使用过时的信息。\n\n"
                    full_system_prompt_with_time = time_prompt + full_system_prompt if full_system_prompt else time_prompt.strip()

                    agent_config_dict = {
                        "name": agent.name,
                        "description": agent.description,
                        "type": agent.type.value if hasattr(agent.type, "value") else str(agent.type),
                        "execution_mode": getattr(agent, "execution_mode", "plan"),
                        "model": agent.model,
                        "temperature": agent.temperature,
                        "max_tokens": agent.max_tokens,
                        "system_prompt": full_system_prompt_with_time,
                        "tools": agent.tools if hasattr(agent, "tools") else [],
                        "mcp_servers": agent.mcp_servers if hasattr(agent, "mcp_servers") else [],
                        "skills": agent.skills if hasattr(agent, "skills") else []
                    }

                    # 如果 agent 启用了长期记忆，注入记忆上下文
                    enable_ltm = getattr(agent, "enable_long_term_memory", False)
                    if enable_ltm and agent_id:
                        agent_config_dict = await _inject_memory_into_agent_config(
                            agent_config_dict, agent_id, message
                        )

                # Get execution mode (backward compat: react_cot maps to react)
                execution_mode = getattr(agent, "execution_mode", "plan") if agent else "plan"
                if execution_mode == "react_cot":
                    execution_mode = "react"
                logger.info(f"Execution mode: {execution_mode}")

                # Mark pending state (for reconnection notification)
                pending_tracker.mark_pending(session_id, message, agent_id=agent_id)

                # Execute LLM — will continue in background if WebSocket disconnects
                full_response = await _run_llm_and_save(
                    session_id=session_id,
                    message=message,
                    history=history,
                    agent_config_dict=agent_config_dict,
                    execution_mode=execution_mode,
                    deep_thinking=current_deep_thinking,
                    agent_id=agent_id,
                    memory_service=memory_service,
                    message_repo=message_repo,
                    websocket=websocket,
                )

            except ValueError as e:
                logger.error(f"ValueError in chat: {e}", exc_info=True)
                try:
                    await websocket.send_json({
                        "type": "error",
                        "content": str(e)
                    })
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Error in chat loop: {e}", exc_info=True)
                try:
                    await websocket.send_json({
                        "type": "error",
                        "content": str(e)
                    })
                except Exception:
                    pass
            finally:
                # Always clear pending state
                pending_tracker.mark_completed(session_id)

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for session {session_id}")
        # 对话结束时提取记忆
        if agent_id and session_id:
            # 检查 agent 是否启用了长期记忆
            try:
                from app.services.agent_service import agent_service as _as
                _agent = await _as.get(agent_id)
                if _agent and getattr(_agent, "enable_long_term_memory", False):
                    try:
                        await _extract_memories_on_session_end(agent_id, session_id, memory_service)
                    except Exception as extract_err:
                        logger.warning(f"Memory extraction failed: {extract_err}")
            except Exception as e:
                logger.warning(f"Failed to trigger memory extraction on disconnect: {e}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "content": str(e)
            })
        except:
            pass

