// Chat Module
const ChatModule = {
    name: 'chat',
    _handlersBound: false,
    _lockedAgentId: null,

    init() {
        // Parse URL params for locked agent_id (params are in hash, e.g., #chat?agent_id=xxx)
        const hash = window.location.hash || '';
        const hashParams = new URLSearchParams(hash.split('?')[1] || '');
        this._lockedAgentId = hashParams.get('agent_id');

        // Load agents
        this.loadAgents();

        // Load sessions
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
        // Just clear the message handlers reference
        this._handlersBound = false;
    },

    bindHandlers() {
        ChatService.on('connected', (data) => {
            ChatView.updateConnectionStatus('connected', '已连接');
            ChatView.setInputsEnabled(true);
            ChatView.showTypingIndicator(false);

            // Load history if we have a session
            if (AppState.get('currentSessionId')) {
                this.loadHistory(AppState.get('currentSessionId'));
            }
        });

        ChatService.on('disconnected', () => {
            ChatView.updateConnectionStatus('disconnected', '已断开');
            ChatView.setInputsEnabled(false);
        });

        ChatService.on('message', (data) => {
            ChatView.showTypingIndicator(false);
            ChatView.createAiMessage();
            ChatView.updateAiMessage(data.content);
        });

        ChatService.on('end', () => {
            ChatView.endAiMessage();
            ChatView.showTypingIndicator(false);
        });

        ChatService.on('error', (data) => {
            ChatView.showTypingIndicator(false);
            ChatView.addMessage('ai', `错误: ${data.content}`);
        });

        ChatService.on('planning', (data) => {
            ChatView.showPlanningCard(data.plan);
        });

        ChatService.on('step_start', (data) => {
            const step = data.step || data;
            if (step.step_number && step.total_steps) {
                ChatView.addPlanningStep(step, step.step_number, step.total_steps);
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
        });

        ChatService.on('thinking_start', () => {
            ChatView.showDeepThinkingContainer();
        });

        ChatService.on('thinking_content', (data) => {
            if (data.content) {
                ChatView.updateDeepThinkingContent(data.content);
            }
        });

        ChatService.on('thinking_end', () => {
            // Keep thinking visible
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
                    ChatView.addMessage(msg.role, msg.content, msg.created_at);
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
            if (this._lockedAgentId) {
                postData.agent_id = this._lockedAgentId;
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

        // Connect WebSocket
        ChatService.connect(sessionId, AppState.get('currentAgentId'));
    },

    async sendMessage() {
        const input = document.getElementById('messageInput');
        const deepThinkingToggle = document.getElementById('deepThinkingToggle');
        const message = input.value.trim();
        const deepThinking = deepThinkingToggle ? deepThinkingToggle.checked : false;

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
        ChatView.showTypingIndicator(true);

        const sent = ChatService.send(message, deepThinking);
        if (!sent) {
            Toast.error('发送失败，请检查连接');
            ChatView.showTypingIndicator(false);
        }
    },

    onAgentChanged(agentId) {
        if (this._lockedAgentId) return;

        AppState.set('currentAgentId', agentId);
        ChatService.setAgent(agentId);

        // Update agent info display
        const agents = AppState.get('agents') || [];
        const agent = agents.find(a => a.id === agentId);
        ChatView.renderActiveAgentInfo(agent);

        // Clear messages when switching agent
        ChatView.clearMessages();
    }
};
