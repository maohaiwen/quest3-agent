// Chat View - UI Rendering
const ChatView = {
    container: null,
    currentAiMessage: null,
    currentAiContent: '',
    thinkingBuffer: '',
    messageCount: 0,

    render(container) {
        this.container = container;
        this.currentAiMessage = null;
        this.currentAiContent = '';
        this.thinkingBuffer = '';
        this.messageCount = 0;

        container.innerHTML = `
            <div class="chat-container" style="display: flex; height: 100%;">
                <!-- Sidebar -->
                <div class="chat-sidebar" style="width: 280px; background: var(--sidebar-bg); border-right: 1px solid var(--border-color); display: flex; flex-direction: column;">
                    <div style="padding: 16px; border-bottom: 1px solid var(--border-color);">
                        <button class="btn btn-primary" style="width: 100%;" onclick="ChatModule.createSession()">
                            ➕ 新建会话
                        </button>
                    </div>
                    <div id="sessionsList" class="sessions-list" style="flex: 1; overflow-y: auto; padding: 8px;">
                        <div class="empty-state">
                            <div class="icon">📝</div>
                            <h3>暂无会话</h3>
                        </div>
                    </div>
                </div>

                <!-- Chat Panel -->
                <div class="chat-panel" style="flex: 1; display: flex; flex-direction: column;">
                    <!-- Header -->
                    <div class="chat-header" style="padding: 16px 24px; border-bottom: 1px solid var(--border-color);">
                        <div style="display: flex; align-items: center; gap: 12px;">
                            <div id="connectionStatus" class="connection-status disconnected">
                                <span class="status-dot disconnected" id="statusDot"></span>
                                <span id="statusText">未连接</span>
                            </div>
                        </div>
                        <div style="margin-top: 12px; display: flex; align-items: center; gap: 8px;">
                            <span style="font-size: 14px; color: var(--text-secondary);">Agent:</span>
                            <select id="agentSelector" class="form-control" style="width: 200px;">
                                <option value="">默认（自动选择）</option>
                            </select>
                            <button class="btn btn-secondary" onclick="Router.navigate('agent')" title="新建Agent">➕</button>
                        </div>
                        <div id="activeAgentInfo" style="margin-top: 8px;"></div>
                    </div>

                    <!-- Messages -->
                    <div id="messagesArea" class="messages-area" style="flex: 1; min-height: 0; overflow-y: auto; padding: 20px;">
                        <div class="empty-state" id="emptyState">
                            <div class="icon">👋</div>
                            <h3>欢迎使用 Quest3 Agent</h3>
                            <p>选择一个会话或创建新会话开始聊天</p>
                        </div>
                        <div class="typing-indicator" id="typingIndicator" style="display: none;">
                            <span>AI正在思考</span>
                            <div class="typing-dots">
                                <span class="typing-dot"></span>
                                <span class="typing-dot"></span>
                                <span class="typing-dot"></span>
                            </div>
                        </div>
                    </div>

                    <!-- Input Area -->
                    <div class="input-area" style="padding: 16px 24px; border-top: 1px solid var(--border-color);">
                        <div class="deep-thinking-toggle" style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px;">
                            <label class="toggle-switch" style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                                <input type="checkbox" id="deepThinkingToggle">
                                <span class="toggle-slider"></span>
                                <span class="toggle-label">深度思考模式</span>
                            </label>
                            <span class="text-muted text-small">开启后先展示思考过程</span>
                        </div>
                        <div style="display: flex; gap: 12px;">
                            <textarea id="messageInput" class="form-control"
                                placeholder="输入您的消息..." disabled
                                style="flex: 1; height: 60px; resize: none;"></textarea>
                            <button id="sendButton" class="btn btn-primary" onclick="ChatModule.sendMessage()" disabled
                                style="height: 60px; padding: 0 24px;">发送</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Bind events
        this._bindEvents();
    },

    _bindEvents() {
        const input = document.getElementById('messageInput');
        if (input) {
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    ChatModule.sendMessage();
                }
            });
        }
    },

    // Session List
    renderSessions(sessions) {
        const list = document.getElementById('sessionsList');
        if (!list) return;

        if (!sessions || sessions.length === 0) {
            list.innerHTML = `
                <div class="empty-state">
                    <div class="icon">📝</div>
                    <h3>暂无会话</h3>
                </div>
            `;
            return;
        }

        const currentSessionId = AppState.get('currentSessionId');
        list.innerHTML = sessions.map(session => {
            const isActive = session.id === currentSessionId;
            return `
            <div class="session-item ${isActive ? 'active' : ''}"
                 onclick="ChatModule.selectSession('${session.id}')"
                 style="padding: 12px; border-radius: 8px; cursor: pointer; margin-bottom: 4px; ${isActive ? 'background: #667eea; color: white;' : 'background: transparent;'}">
                <div style="font-size: 14px; font-weight: 500;">${this.escapeHtml(session.title || '新会话')}</div>
                <div style="font-size: 12px; opacity: ${isActive ? '0.8' : '0.7'};">${this.formatDate(session.created_at)}</div>
            </div>
        `}).join('');
    },

    // Agent Selector
    renderAgentSelector(agents) {
        const selector = document.getElementById('agentSelector');
        if (!selector) return;

        const currentAgentId = AppState.get('currentAgentId');

        selector.innerHTML = `<option value="">默认（自动选择）</option>` +
            agents.map(agent =>
                `<option value="${agent.id}" ${agent.id === currentAgentId ? 'selected' : ''}>
                    ${this.escapeHtml(agent.name)} (${agent.type})
                </option>`
            ).join('');
    },

    // Active Agent Info
    renderActiveAgentInfo(agent) {
        const info = document.getElementById('activeAgentInfo');
        if (!info) return;

        if (!agent) {
            info.innerHTML = '<div style="font-size: 13px; color: var(--text-muted);">使用默认Agent</div>';
            return;
        }

        const modeIcon = agent.execution_mode === 'react' ? '🔄' : '📋';
        info.innerHTML = `
            <div style="display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px;
                        background: rgba(102, 126, 234, 0.2); border-radius: 16px; font-size: 13px;">
                <span>${modeIcon}</span>
                <span style="font-weight: 500;">${this.escapeHtml(agent.name)}</span>
                <span style="color: var(--text-secondary);">(${agent.type})</span>
            </div>
        `;
    },

    // Hide Agent Selector (when locked to a specific agent)
    hideAgentSelector() {
        const selectorContainer = document.getElementById('agentSelector')?.parentElement;
        if (selectorContainer) {
            selectorContainer.innerHTML = `
                <span style="font-size: 14px; color: var(--text-secondary);">Agent:</span>
                <span style="font-weight: 500; color: var(--primary);">已锁定</span>
            `;
        }
        const addButton = document.querySelector('.chat-header .btn.btn-secondary');
        if (addButton) {
            addButton.style.display = 'none';
        }
    },

    // Connection Status
    updateConnectionStatus(status, text) {
        const statusDiv = document.getElementById('connectionStatus');
        const dot = document.getElementById('statusDot');
        const textEl = document.getElementById('statusText');
        if (!statusDiv || !dot || !textEl) return;

        statusDiv.className = `connection-status ${status}`;
        dot.className = `status-dot ${status}`;
        textEl.textContent = text;
    },

    // Inputs
    setInputsEnabled(enabled) {
        const input = document.getElementById('messageInput');
        const sendBtn = document.getElementById('sendButton');
        if (input) input.disabled = !enabled;
        if (sendBtn) sendBtn.disabled = !enabled;
        if (enabled && input) input.focus();
    },

    // Typing Indicator
    showTypingIndicator(show) {
        const indicator = document.getElementById('typingIndicator');
        if (indicator) {
            indicator.style.display = show ? 'flex' : 'none';
            if (show) {
                indicator.scrollIntoView({ behavior: 'smooth', block: 'end' });
            }
        }
    },

    // Clear Empty State
    clearEmptyState() {
        const empty = document.getElementById('emptyState');
        if (empty) empty.remove();
    },

    // Add Message
    addMessage(sender, content, timestamp = null) {
        this.clearEmptyState();

        const messagesArea = document.getElementById('messagesArea');
        if (!messagesArea) return;

        const timeStr = timestamp
            ? new Date(timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
            : new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });

        const avatarIcon = sender === 'user' ? '👤' : sender === 'ai' ? '🤖' : '⚙️';
        const avatarClass = sender === 'user' ? 'user' : sender === 'ai' ? 'ai' : '';

        const messageDiv = document.createElement('div');
        messageDiv.className = 'message';
        messageDiv.innerHTML = `
            <div class="message-header">
                <span class="message-avatar ${avatarClass}">${avatarIcon}</span>
                <span class="message-sender">${sender === 'user' ? '我' : 'AI'}</span>
                <span class="message-time">${timeStr}</span>
            </div>
            <div class="message-content">${this.escapeHtml(content)}</div>
        `;

        const indicator = document.getElementById('typingIndicator');
        messagesArea.insertBefore(messageDiv, indicator);
        messageDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });

        return messageDiv;
    },

    // Create AI Message Element (for streaming)
    createAiMessage() {
        // If AI message already exists, reuse it instead of creating a new one
        if (this.currentAiMessage) {
            return this.currentAiMessage;
        }

        this.clearEmptyState();

        const messagesArea = document.getElementById('messagesArea');
        if (!messagesArea) return null;

        const messageDiv = document.createElement('div');
        messageDiv.className = 'message';
        messageDiv.innerHTML = `
            <div class="message-header">
                <span class="message-avatar ai">🤖</span>
                <span class="message-sender">AI</span>
                <span class="message-time">${new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>
            </div>
            <div class="message-content"></div>
        `;

        const indicator = document.getElementById('typingIndicator');
        messagesArea.insertBefore(messageDiv, indicator);
        messageDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });

        this.currentAiMessage = messageDiv;
        this.currentAiContent = '';

        return messageDiv;
    },

    // Update AI Message Content
    updateAiMessage(content) {
        if (!this.currentAiMessage) return;
        const contentDiv = this.currentAiMessage.querySelector('.message-content');
        if (contentDiv) {
            this.currentAiContent += content;
            contentDiv.textContent = this.currentAiContent;
        }
        const messagesArea = document.getElementById('messagesArea');
        if (messagesArea) this.currentAiMessage?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    },

    // End AI Message
    endAiMessage() {
        if (this.currentAiMessage) {
            this.messageCount++;
        }
        this.currentAiMessage = null;
        this.currentAiContent = '';
        this.thinkingBuffer = '';
    },

    // Deep Thinking Container
    showDeepThinkingContainer() {
        const messagesArea = document.getElementById('messagesArea');
        if (!messagesArea) return null;

        const container = document.createElement('div');
        container.className = 'deep-thinking-container';
        container.id = 'deepThinkingContainer';
        container.innerHTML = `
            <div class="deep-thinking-header">
                <span class="deep-thinking-icon">🧠</span>
                <span class="deep-thinking-title">深度思考过程</span>
            </div>
            <div class="deep-thinking-content">
                <div class="thinking-text"></div>
            </div>
        `;

        const indicator = document.getElementById('typingIndicator');
        messagesArea.insertBefore(container, indicator);
        container.scrollIntoView({ behavior: 'smooth', block: 'end' });

        this.thinkingBuffer = '';
        return container;
    },

    updateDeepThinkingContent(content) {
        const container = document.getElementById('deepThinkingContainer');
        if (!container) return;

        this.thinkingBuffer += content;
        const textDiv = container.querySelector('.thinking-text');
        if (textDiv) {
            textDiv.textContent = this.thinkingBuffer;
        }

        container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    },

    removeDeepThinkingContainer() {
        const container = document.getElementById('deepThinkingContainer');
        if (container) container.remove();
        this.thinkingBuffer = '';
        // Scroll to AI message after removing thinking container
        if (this.currentAiMessage) {
            this.currentAiMessage.scrollIntoView({ behavior: 'smooth', block: 'end' });
        }
    },

    // Execution Events
    showPlanningCard(plan) {
        const messagesArea = document.getElementById('messagesArea');
        if (!messagesArea) return;

        const card = document.createElement('div');
        card.className = 'planning-card';
        card.id = 'planningCard';

        const totalSteps = plan.total_steps || plan.step_count || 0;
        const complexity = plan.complexity || 'UNKNOWN';
        const strategy = plan.strategy || 'unknown';

        card.innerHTML = `
            <div class="planning-header">
                <span>📋 智能规划</span>
                <div class="planning-badges">
                    <span class="planning-badge complexity">${complexity}</span>
                    <span class="planning-badge strategy">${strategy}</span>
                </div>
            </div>
            ${plan.description ? `<div class="planning-description">${this.escapeHtml(plan.description)}</div>` : ''}
            ${totalSteps > 0 ? `
                <div class="planning-steps">
                    <div class="planning-steps-title">📝 执行步骤:</div>
                    <div id="planningStepsContainer"></div>
                </div>
            ` : `
                <div class="planning-no-steps">
                    <span class="planning-no-steps-icon">ℹ️</span>
                    <span class="planning-no-steps-text">无需使用工具，将直接回复</span>
                </div>
            `}
        `;

        const indicator = document.getElementById('typingIndicator');
        messagesArea.insertBefore(card, indicator);
        card.scrollIntoView({ behavior: 'smooth', block: 'end' });
    },

    addPlanningStep(step, stepNumber, totalSteps) {
        const container = document.getElementById('planningStepsContainer');
        if (!container) return;

        const stepDiv = document.createElement('div');
        stepDiv.className = 'planning-step-item';
        stepDiv.id = `step-${step.step_id}`;
        stepDiv.innerHTML = `
            <div class="planning-step-main">
                <span class="planning-step-number">${stepNumber}.</span>
                <span class="planning-step-tool">${step.tool_name || step.tool || 'Unknown'}</span>
                <span class="planning-step-status" id="step-status-${step.step_id}"></span>
            </div>
            ${step.arguments && Object.keys(step.arguments).length > 0 ?
                `<div class="planning-step-args">${JSON.stringify(step.arguments, null, 2)}</div>` : ''}
            <div class="planning-step-result" id="step-result-${step.step_id}"></div>
        `;
        container.appendChild(stepDiv);
        stepDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });
    },

    updateStepStatus(stepId, status, text) {
        const statusEl = document.getElementById(`step-status-${stepId}`);
        if (statusEl) {
            statusEl.className = `planning-step-status ${status}`;
            statusEl.textContent = text;
        }
    },

    updateStepResult(stepId, result) {
        const resultEl = document.getElementById(`step-result-${stepId}`);
        if (resultEl && result) {
            const content = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
            resultEl.innerHTML = `<div class="step-result-inline">${this.escapeHtml(content.substring(0, 200))}${content.length > 200 ? '...' : ''}</div>`;
        }
    },

    // Utility
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    formatDate(dateString) {
        if (!dateString) return '';
        const date = new Date(dateString);
        const now = new Date();
        const diff = now - date;

        if (diff < 60000) return '刚刚';
        if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`;
        if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`;
        return date.toLocaleDateString('zh-CN');
    },

    clearMessages() {
        const messagesArea = document.getElementById('messagesArea');
        if (!messagesArea) return;

        const indicator = document.getElementById('typingIndicator');
        messagesArea.innerHTML = '';
        if (indicator) messagesArea.appendChild(indicator);

        this.currentAiMessage = null;
        this.currentAiContent = '';
        this.thinkingBuffer = '';
        this.messageCount = 0;
    }
};

// Add chat-specific styles
const chatStyles = document.createElement('style');
chatStyles.textContent = `
    .connection-status {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        padding: 4px 12px;
        border-radius: 20px;
    }
    .connection-status.connected { background: var(--success-bg); color: var(--success-color); }
    .connection-status.disconnected { background: var(--error-bg); color: var(--error-color); }
    .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
    }
    .status-dot.connected { background: #4caf50; }
    .status-dot.disconnected { background: #dc3545; }

    .toggle-switch input[type="checkbox"] { display: none; }
    .toggle-slider {
        width: 44px;
        height: 24px;
        background: #ccc;
        border-radius: 12px;
        position: relative;
        transition: background 0.3s;
    }
    .toggle-slider::before {
        content: '';
        position: absolute;
        width: 20px;
        height: 20px;
        background: white;
        border-radius: 50%;
        top: 2px;
        left: 2px;
        transition: transform 0.3s;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
    }
    .toggle-switch input[type="checkbox"]:checked + .toggle-slider {
        background: var(--primary);
    }
    .toggle-switch input[type="checkbox"]:checked + .toggle-slider::before {
        transform: translateX(20px);
    }

    .deep-thinking-container {
        background: #f8f9fa;
        border-left: 4px solid var(--primary);
        border-radius: 8px;
        margin: 16px 0;
        overflow: hidden;
    }
    .deep-thinking-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 12px 16px;
        background: rgba(102, 126, 234, 0.1);
        border-bottom: 1px solid var(--border-color);
    }
    .deep-thinking-icon { font-size: 18px; }
    .deep-thinking-title { font-weight: 600; color: #333; font-size: 14px; }
    .deep-thinking-content { padding: 12px 16px; }
    .thinking-text { font-size: 13px; color: #333; line-height: 1.6; white-space: pre-wrap; }

    .planning-card {
        background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
        border: 1px solid #d1d5db;
        border-radius: 10px;
        padding: 15px;
        margin: 10px 0;
    }
    .planning-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
    }
    .planning-badges { display: flex; gap: 8px; }
    .planning-badge {
        font-size: 11px;
        padding: 3px 8px;
        border-radius: 10px;
        font-weight: 500;
    }
    .planning-badge.complexity { background: #e3f2fd; color: #1565c0; }
    .planning-badge.strategy { background: #f3e5f5; color: #7b1fa2; }
    .planning-description {
        font-size: 13px;
        color: #666;
        margin: 8px 0;
        padding: 8px 10px;
        background: rgba(255,255,255,0.7);
        border-radius: 6px;
        border-left: 3px solid var(--primary);
    }
    .planning-steps-title { font-size: 13px; font-weight: 600; color: #333; margin-bottom: 8px; }
    .planning-step-item {
        background: white;
        padding: 10px 12px;
        margin: 6px 0;
        border-radius: 8px;
        border-left: 3px solid var(--primary);
    }
    .planning-step-main { display: flex; align-items: center; gap: 10px; }
    .planning-step-number { font-weight: 600; color: var(--primary); }
    .planning-step-tool { color: #333; font-weight: 500; }
    .planning-step-status { margin-left: auto; font-size: 12px; }
    .planning-step-status.running { color: #f57c00; }
    .planning-step-status.complete { color: #388e3c; }
    .planning-step-status.error { color: #d32f2f; }
    .planning-step-args {
        font-size: 12px;
        color: #666;
        margin-top: 6px;
        background: #f8f9fa;
        padding: 6px;
        border-radius: 4px;
        white-space: pre-wrap;
    }
    .planning-step-result { margin-top: 6px; }
    .step-result-inline { font-size: 12px; color: #666; white-space: pre-wrap; }
    .planning-no-steps {
        margin-top: 12px;
        padding: 8px 12px;
        background: #e8f5e9;
        border-radius: 6px;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .typing-indicator {
        display: flex;
        align-items: center;
        gap: 5px;
        color: #999;
        padding: 0 40px;
    }
    .typing-dots { display: flex; gap: 3px; }
    .typing-dot {
        width: 6px;
        height: 6px;
        background: #999;
        border-radius: 50%;
        animation: typingBounce 1.4s infinite;
    }
    .typing-dot:nth-child(2) { animation-delay: 0.2s; }
    .typing-dot:nth-child(3) { animation-delay: 0.4s; }
    @keyframes typingBounce {
        0%, 60%, 100% { transform: translateY(0); }
        30% { transform: translateY(-6px); }
    }
`;
document.head.appendChild(chatStyles);
