// Chat Module
const ChatModule = {
    name: 'chat',
    _handlersBound: false,
    _lockedAgentId: null,

    async init() {
        // Parse URL params for locked agent_id (params are in hash, e.g., #chat?agent_id=xxx)
        const hash = window.location.hash || '';
        const hashParams = new URLSearchParams(hash.split('?')[1] || '');
        this._lockedAgentId = hashParams.get('agent_id');

        // Load agents FIRST (must complete before sessions, so currentAgentId is set)
        await this.loadAgents();

        // Then load sessions (which may auto-select and connect WebSocket)
        this.loadSessions();

        // Bind WebSocket handlers only once
        if (!this._handlersBound) {
            this.bindHandlers();
            this._handlersBound = true;
        }

        // Bind agent selector change event (only if not locked to a specific agent)
        if (!this._lockedAgentId) {
            setTimeout(() => {
                const agentSelector = document.getElementById('agentSelector');
                if (agentSelector) {
                    agentSelector.addEventListener('change', (e) => {
                        const agentId = e.target.value || null;
                        this.onAgentChanged(agentId);
                    });
                }
            }, 0);
        }
    },

    render(container) {
        ChatView.render(container);
    },

    destroy() {
        // Don't disconnect WebSocket on route change - keep connection alive
        // Don't reset _handlersBound - handlers are already bound to ChatService
        // and should persist across route changes to avoid duplicate registrations
    },

    bindHandlers() {
        ChatService.on('connected', (data) => {
            ChatView.updateConnectionStatus('connected', '已连接');
            ChatView.setInputsEnabled(true);
            ChatView.showTypingIndicator(false);
        });

        ChatService.on('history', (data) => {
            // Server sends history via WebSocket after connection
            ChatView.clearMessages();
            if (data.messages && data.messages.length > 0) {
                data.messages.forEach(msg => {
                    // Map "assistant" role from backend to "ai" for frontend rendering
                    const sender = msg.role === 'assistant' ? 'ai' : msg.role;
                    ChatView.addMessage(sender, msg.content, msg.created_at);
                });
            }
            // Show "load more" button if there are older messages
            if (data.has_more) {
                ChatView.showLoadMoreButton();
            }
        });

        ChatService.on('more_history', (data) => {
            if (data.messages && data.messages.length > 0) {
                ChatView.prependMessages(data.messages);
            }
            if (!data.has_more) {
                ChatView.hideLoadMoreButton();
            }
        });

        ChatService.on('disconnected', () => {
            ChatView.updateConnectionStatus('disconnected', '已断开');
            // If AI was responding when disconnected, finalize the message
            // to prevent input being permanently greyed out
            if (ChatView._aiResponding) {
                ChatView.finalizeAiMessage();
            }
            ChatView.setInputsEnabled(false);
        });

        // Direct mode streaming
        ChatService.on('message', (data) => {
            ChatView.showTypingIndicator(false);
            if (!ChatView._aiResponding) {
                ChatView.startAiResponse();
            }
            ChatView.updateAiMessage(data.content);
        });

        // End of response (all modes)
        ChatService.on('end', () => {
            ChatView.showTypingIndicator(false);
            ChatView.finalizeAiMessage();
        });

        ChatService.on('error', (data) => {
            ChatView.showTypingIndicator(false);
            if (ChatView._aiResponding) {
                ChatView.finalizeAiMessage();
            }
            ChatView.addMessage('ai', `错误: ${data.content || data.message || '未知错误'}`);
        });

        // Plan/React mode
        ChatService.on('planning', (data) => {
            if (!ChatView._aiResponding) {
                ChatView.startAiResponse();
            }
            ChatView.showPlanningCard(data.plan);
        });

        ChatService.on('step_start', (data) => {
            const step = data.step || data;
            // Add step to planning card if there's a steps container
            const hasStepsContainer = document.querySelector('.planning-steps-container:last-of-type');
            if (hasStepsContainer) {
                const stepNumber = step.step_number || 1;
                const totalSteps = step.total_steps || 1;
                ChatView.addPlanningStep(step, stepNumber, totalSteps);
            }
            ChatView.updateStepStatus(step.step_id, 'running', '⏳ 执行中');
        });

        ChatService.on('step_complete', (data) => {
            ChatView.updateStepStatus(data.step_id, 'complete', '✅ 完成');
            if (data.result) {
                ChatView.updateStepResult(data.step_id, data.result);
            }
        });

        ChatService.on('step_error', (data) => {
            ChatView.updateStepStatus(data.step_id, 'error', '❌ 失败');
            if (data.error) {
                ChatView.updateStepResult(data.step_id, `错误: ${data.error}`);
            }
        });

        ChatService.on('thinking_start', () => {
            if (!ChatView._aiResponding) {
                ChatView.startAiResponse();
            }
            // Don't create deep-thinking container here — it will be created
            // lazily when actual thinking content arrives
        });

        ChatService.on('thinking_content', (data) => {
            if (data.content) {
                if (!ChatView._cotContainer) {
                    ChatView.showDeepThinkingContainer();
                }
                ChatView.updateDeepThinkingContent(data.content);
            }
        });

        ChatService.on('thinking', (data) => {
            // Handle thinking events from strategy_router (direct mode)
            const content = data.content || data.message;
            if (content) {
                if (!ChatView._cotContainer) {
                    ChatView.showDeepThinkingContainer();
                }
                ChatView.updateDeepThinkingContent(content);
            }
        });

        ChatService.on('thinking_end', () => {
            // Keep thinking visible
        });

        // COT mode (ReActCotExecutor)
        ChatService.on('cot_step_start', (data) => {
            if (!ChatView._aiResponding) {
                ChatView.startAiResponse();
            }
            ChatView.showDeepThinkingContainer();
        });

        ChatService.on('cot_phase', (data) => {
            ChatView.updateThinkingPhase(data.phase);
        });

        ChatService.on('cot_thinking', (data) => {
            if (data.content) {
                ChatView.updateDeepThinkingContent(data.content);
            }
        });

        ChatService.on('cot_action', (data) => {
            ChatView.addThinkingToolCall(data.tool_name, data.tool_args);
        });

        ChatService.on('cot_observation', (data) => {
            ChatView.updateThinkingToolResult(data.result);
        });

        ChatService.on('cot_complete', (data) => {
            ChatView.updateThinkingPhase('complete');
            ChatView.showTypingIndicator(false);
            if (data.message && !data.streamed) {
                // 内容未流式发送（答案在 thinking 中），一次性设置
                ChatView.setAiMessage(data.message);
            }
        });
    },

    async loadAgents() {
        try {
            const data = await API.get('/api/agents?enabled_only=true');
            AppState.set('agents', data.agents || []);
            ChatView.renderAgentSelector(data.agents || []);

            // If locked to a specific agent, use that one
            if (this._lockedAgentId) {
                const agents = data.agents || [];
                const lockedAgent = agents.find(a => a.id === this._lockedAgentId);
                if (lockedAgent) {
                    AppState.set('currentAgentId', lockedAgent.id);
                    ChatView.renderActiveAgentInfo(lockedAgent);
                    ChatView.hideAgentSelector();
                }
            } else {
                // Auto-select first agent
                const agents = data.agents || [];
                if (agents.length > 0 && !AppState.get('currentAgentId')) {
                    const firstAgent = agents[0];
                    AppState.set('currentAgentId', firstAgent.id);
                    ChatView.renderActiveAgentInfo(firstAgent);
                }
            }
        } catch (error) {
            console.error('Failed to load agents:', error);
            Toast.error('加载Agent列表失败');
        }
    },

    async loadSessions() {
        try {
            const agentId = this._lockedAgentId;
            let url = '/api/sessions/list/all';
            if (agentId) {
                url = `/api/sessions/list/by-agent/${agentId}`;
            }
            const data = await API.get(url);
            const sessions = data.sessions || [];
            AppState.set('sessions', sessions);
            ChatView.renderSessions(sessions);

            // Auto-select latest session if none selected
            if (!AppState.get('currentSessionId') && sessions.length > 0) {
                const sortedSessions = [...sessions].sort((a, b) =>
                    new Date(b.created_at) - new Date(a.created_at)
                );
                this.selectSession(sortedSessions[0].id);
            }
        } catch (error) {
            console.error('Failed to load sessions:', error);
        }
    },

    async loadHistory(sessionId) {
        try {
            ChatView.clearMessages();
            const data = await API.get(`/api/sessions/${sessionId}/history`);
            if (data.messages && data.messages.length > 0) {
                data.messages.forEach(msg => {
                    const sender = msg.role === 'assistant' ? 'ai' : msg.role;
                    ChatView.addMessage(sender, msg.content, msg.created_at);
                });
            }
        } catch (error) {
            console.error('Failed to load history:', error);
        }
    },

    async createSession() {
        try {
            const postData = {
                title: `会话 ${new Date().toLocaleString('zh-CN')}`
            };
            // Include the currently selected agent (locked or from dropdown)
            const agentId = this._lockedAgentId || AppState.get('currentAgentId');
            if (agentId) {
                postData.agent_id = agentId;
            }
            const data = await API.post('/api/sessions/create', postData);
            if (data.session_id) {
                Toast.success('会话已创建');
                await this.loadSessions();
                this.selectSession(data.session_id);
                // History will be loaded by ChatService connected handler
            }
        } catch (error) {
            console.error('Failed to create session:', error);
            Toast.error('创建会话失败');
        }
    },

    selectSession(sessionId) {
        AppState.set('currentSessionId', sessionId);
        const sessions = AppState.get('sessions') || [];
        ChatView.renderSessions(sessions);

        // Get agent_id: from current selection, or from the session's associated agent
        let agentId = AppState.get('currentAgentId');
        if (!agentId) {
            const session = sessions.find(s => s.id === sessionId);
            if (session && session.agent_id) {
                agentId = session.agent_id;
                AppState.set('currentAgentId', agentId);
            }
        }

        // Connect WebSocket
        ChatService.connect(sessionId, agentId);
    },

    async sendMessage() {
        const input = document.getElementById('messageInput');
        const message = input.value.trim();
        // Read deep thinking toggle (only relevant for direct mode)
        const deepThinkingCheckbox = document.getElementById('deepThinkingCheckbox');
        const deepThinking = deepThinkingCheckbox ? deepThinkingCheckbox.checked : false;

        if (!message) return;

        if (!AppState.get('currentSessionId')) {
            Toast.warning('请先创建或选择一个会话');
            return;
        }

        if (!ChatService.isConnected) {
            Toast.error('连接已断开，请等待重连');
            return;
        }

        // Add user message
        ChatView.addMessage('user', message);
        input.value = '';
        ChatView._setSendEnabled(false);
        ChatView.showTypingIndicator(true);

        const sent = ChatService.send(message, deepThinking);
        if (!sent) {
            Toast.error('发送失败，请检查连接');
            ChatView.showTypingIndicator(false);
        }
    },

    onAgentChanged(agentId) {
        if (this._lockedAgentId) return;

        AppState.set('currentAgentId', agentId || null);
        ChatService.setAgent(agentId);

        // Update agent info display
        if (agentId) {
            const agents = AppState.get('agents') || [];
            const agent = agents.find(a => a.id === agentId);
            ChatView.renderActiveAgentInfo(agent);
        } else {
            ChatView.renderActiveAgentInfo(null);
        }

        // Clear messages when switching agent
        ChatView.clearMessages();
    },

    loadMoreHistory() {
        ChatService.loadMoreHistory(40);
    }
};
