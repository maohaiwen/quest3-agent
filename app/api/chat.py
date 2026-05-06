"""Chat API endpoints"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from typing import List, Optional
import json
import logging
from datetime import datetime

from app.models.chat import ChatRequest, ChatResponse, StreamMessage, MessageCreate, MessageRole
from app.database.repositories import MessageRepository, SessionRepository
from app.services.llm_service import LLMService
from app.services.session_working_memory import SessionWorkingMemory
from app.services.planning_chat_service import planning_chat_service
from app.core.strategy_router import strategy_router

logger = logging.getLogger(__name__)


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

                # Use strategy router for direct mode
                if execution_mode == "direct":
                    full_response = ""
                    event_count = 0
                    sent_events = []

                    logger.info(f"Starting strategy_router.execute() for message: {message[:50]}...")

                    try:
                        # Get generator
                        gen = strategy_router.execute(
                            message,
                            agent_config=agent_config_dict,
                            conversation_history=history,
                            deep_thinking=current_deep_thinking
                        )
                        logger.info("Generator created, starting iteration...")

                        async for event in gen:
                            event_count += 1
                            event_type = event.get('type')
                            logger.info(f"Iteration {event_count}: Received event '{event_type}' from strategy_router")

                            try:
                                await websocket.send_json(event)
                                sent_events.append(event_type)
                                logger.info(f"Iteration {event_count}: Event '{event_type}' sent to client successfully")
                            except Exception as send_error:
                                logger.error(f"Iteration {event_count}: Failed to send event '{event_type}': {send_error}", exc_info=True)
                                raise

                            if event_type == "message":
                                full_response += event.get("content", "")

                        logger.info(f"Strategy router generator completed. Total iterations: {event_count}")

                    except Exception as e:
                        logger.error(f"Error in strategy_router.execute() loop: {e}", exc_info=True)
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Execution error: {str(e)}"
                        })
                        return

                    finally:
                        # Always ensure end event is sent
                        logger.info(f"Finally block executing... Sent event types: {sent_events}")
                        if 'end' not in sent_events:
                            logger.warning(f"Finally: 'end' event NOT sent! (total: {len(sent_events)} events). Sending fallback.")
                            try:
                                await websocket.send_json({"type": "end"})
                                sent_events.append("end")
                                logger.info(f"Finally: Fallback 'end' event sent successfully (total: {len(sent_events)} events)")
                            except Exception as e:
                                logger.error(f"Finally: Failed to send fallback 'end' event: {e}", exc_info=True)
                        else:
                            logger.info(f"Finally: 'end' event was sent (total: {len(sent_events)} events)")

                    # Save assistant message
                    if full_response:
                        await message_repo.create(MessageCreate(
                            session_id=session_id,
                            content=full_response,
                            role=MessageRole.ASSISTANT
                        ))

                        # Add to memory
                        await _add_assistant_message(memory_service, session_id, full_response, agent_model=agent_config_dict.get("model"))
                elif execution_mode in ["plan", "react"]:
                    logger.info(f"Using execution mode: {execution_mode}")

                    if execution_mode == "react":
                        # ReAct 模式：思考-行动-观察循环
                        logger.info("Using ReActCotExecutor for react mode")
                        from app.core.react_cot_executor import ReActCotExecutor

                        # 添加 thinking_effort 到配置
                        if agent_config_dict:
                            agent_config_dict["thinking_effort"] = getattr(agent, "thinking_effort", "medium")
                            agent_config_dict["max_react_steps"] = getattr(agent, "max_react_steps", 15)

                        executor = ReActCotExecutor(agent_config=agent_config_dict)

                        full_response = ""
                        sent_end = False
                        try:
                            async for event in executor.execute(
                                message,
                                conversation_history=history,
                                deep_thinking=True
                            ):
                                await websocket.send_json(event)
                                if event.get("type") == "cot_complete":
                                    full_response = event.get("message", "") or full_response
                                if event.get("type") == "end":
                                    sent_end = True
                        except Exception as e:
                            logger.error(f"ReAct execution error: {e}", exc_info=True)
                            try:
                                await websocket.send_json({
                                    "type": "error",
                                    "content": f"执行错误: {str(e)}"
                                })
                            except:
                                pass
                        finally:
                            if not sent_end:
                                try:
                                    await websocket.send_json({"type": "end"})
                                except:
                                    pass

                        # Save assistant message
                        if full_response:
                            await message_repo.create(MessageCreate(
                                session_id=session_id,
                                content=full_response,
                                role=MessageRole.ASSISTANT
                            ))
                            await _add_assistant_message(memory_service, session_id, full_response, agent_model=agent_config_dict.get("model"))

                    else:
                        # plan 模式：先规划再执行
                        from app.services.planning_chat_service import planning_chat_service

                        actual_deep_thinking = True
                        logger.info("Plan mode: forcing deep thinking enabled")

                        full_response = ""
                        async for event in planning_chat_service.chat(
                            message,
                            conversation_history=history,
                            enable_planning=True,
                            use_react=False,
                            agent_config=agent_config_dict,
                            deep_thinking=actual_deep_thinking
                        ):
                            await websocket.send_json(event)
                            if event.get("type") == "message":
                                full_response += event.get("content", "")

                        # Save assistant message
                        if full_response:
                            await message_repo.create(MessageCreate(
                                session_id=session_id,
                                content=full_response,
                                role=MessageRole.ASSISTANT
                            ))
                            await _add_assistant_message(memory_service, session_id, full_response, agent_model=agent_config_dict.get("model"))

            except ValueError as e:
                logger.error(f"ValueError in chat: {e}", exc_info=True)
                await websocket.send_json({
                    "type": "error",
                    "content": str(e)
                })
            except Exception as e:
                logger.error(f"Error in chat loop: {e}", exc_info=True)
                try:
                    await websocket.send_json({
                        "type": "error",
                        "content": str(e)
                    })
                except:
                    pass

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

