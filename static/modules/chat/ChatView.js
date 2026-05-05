// Chat View - UI Rendering
const ChatView = {
    container: null,
    messageCount: 0,

    // Per-round state — all reset at the start of each AI response
    _roundId: 0,           // monotonically increasing, used for unique DOM IDs
    _aiMessageEl: null,     // current AI message div
    _aiContent: '',         // accumulated AI content for this round
    _cotContainer: null,    // current deep-thinking container
    _cotStep: 0,            // current COT step number
    _cotNextStepNeeded: false,  // flag: next "thinking" phase should create new step
    _cotThinkingEl: null,   // current step's thinking text element
    _thinkingBuffer: '',    // accumulated thinking text for current step
    _aiResponding: false,   // whether AI is currently responding

    render(container) {
        this.container = container;
        this._resetRoundState();
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
                        <div style="display: flex; gap: 12px; align-items: flex-end;">
                            <div style="flex: 1; display: flex; flex-direction: column; gap: 8px;">
                                <textarea id="messageInput" class="form-control"
                                    placeholder="输入您的消息..." disabled
                                    style="flex: 1; height: 60px; resize: none;"></textarea>
                                <div id="deepThinkingRow" class="deep-thinking-toggle-row" style="display: none;">
                                    <label class="deep-thinking-switch" for="deepThinkingCheckbox">
                                        <input type="checkbox" id="deepThinkingCheckbox">
                                        <span class="deep-thinking-slider"></span>
                                    </label>
                                    <span class="deep-thinking-label">深度思考</span>
                                </div>
                            </div>
                            <button id="sendButton" class="btn btn-primary" onclick="ChatModule.sendMessage()" disabled
                                style="height: 60px; padding: 0 24px;">发送</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

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

    // ═══════════════════════════════════════
    // Round lifecycle management
    // ═══════════════════════════════════════

    _resetRoundState() {
        this._roundId++;
        this._aiMessageEl = null;
        this._aiContent = '';
        this._cotContainer = null;
        this._cotStep = 0;
        this._cotNextStepNeeded = false;
        this._cotThinkingEl = null;
        this._thinkingBuffer = '';
        this._aiResponding = false;
    },

    /** Called when AI starts a new response — finalizes any previous round */
    startAiResponse() {
        if (this._aiResponding) {
            this.finalizeAiMessage();
        }
        this._resetRoundState();
        this._aiResponding = true;
        this._setSendEnabled(false);
    },

    /** Finalize the current AI message (render markdown, lock it down) */
    finalizeAiMessage() {
        if (this._aiMessageEl) {
            const contentDiv = this._aiMessageEl.querySelector('.message-content');
            if (contentDiv && this._aiContent) {
                contentDiv.innerHTML = this._renderMarkdown(this._aiContent);
            }
            this.messageCount++;
        }
        this._aiMessageEl = null;
        this._aiContent = '';
        this._aiResponding = false;
        this._setSendEnabled(true);
    },

    _setSendEnabled(enabled) {
        const input = document.getElementById('messageInput');
        const sendBtn = document.getElementById('sendButton');
        if (sendBtn) sendBtn.disabled = !enabled;
        // Don't re-enable input when connected — only when AI is done
        if (input) input.disabled = !enabled;
        if (enabled && input) input.focus();
    },

    // ═══════════════════════════════════════
    // Message rendering
    // ═══════════════════════════════════════

    _renderMarkdown(text) {
        if (!text) return '';
        if (typeof marked !== 'undefined') {
            try {
                return marked.parse(text);
            } catch (e) { /* fall through */ }
        }
        return this.escapeHtml(text).replace(/\n/g, '<br>');
    },

    /** Add a static (historical) message */
    addMessage(sender, content, timestamp = null) {
        this._clearEmptyState();

        const messagesArea = document.getElementById('messagesArea');
        if (!messagesArea) return;

        const timeStr = timestamp
            ? new Date(timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
            : new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });

        const avatarIcon = sender === 'user' ? '👤' : sender === 'ai' ? '🤖' : '⚙️';
        const avatarClass = sender === 'user' ? 'user' : sender === 'ai' ? 'ai' : '';
        const renderedContent = sender === 'ai' ? this._renderMarkdown(content) : this.escapeHtml(content);

        const messageDiv = document.createElement('div');
        messageDiv.className = 'message';
        messageDiv.innerHTML = `
            <div class="message-header">
                <span class="message-avatar ${avatarClass}">${avatarIcon}</span>
                <span class="message-sender">${sender === 'user' ? '我' : 'AI'}</span>
                <span class="message-time">${timeStr}</span>
            </div>
            <div class="message-content">${renderedContent}</div>
        `;

        const indicator = document.getElementById('typingIndicator');
        messagesArea.insertBefore(messageDiv, indicator);
        messageDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });
        return messageDiv;
    },

    /** Create a NEW AI message div (always fresh, never reuse) */
    _createAiMessageEl() {
        const messagesArea = document.getElementById('messagesArea');
        if (!messagesArea) return null;

        this._clearEmptyState();

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

        this._aiMessageEl = messageDiv;
        this._aiContent = '';

        messageDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });
        return messageDiv;
    },

    /** Append content to the current AI message */
    updateAiMessage(content) {
        if (!this._aiMessageEl) {
            this._createAiMessageEl();
        }
        const contentDiv = this._aiMessageEl.querySelector('.message-content');
        if (contentDiv) {
            this._aiContent += content;
            contentDiv.innerHTML = this._renderMarkdown(this._aiContent);
        }
        this._aiMessageEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    },

    /** Set the entire AI message content at once (replaces, not appends) */
    setAiMessage(content) {
        if (!this._aiMessageEl) {
            this._createAiMessageEl();
        }
        const contentDiv = this._aiMessageEl.querySelector('.message-content');
        if (contentDiv) {
            this._aiContent = content;
            contentDiv.innerHTML = this._renderMarkdown(this._aiContent);
        }
        this._aiMessageEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    },

    // ═══════════════════════════════════════
    // COT / Deep-thinking container
    // ═══════════════════════════════════════

    _uniqueId(base) {
        return `${base}-r${this._roundId}`;
    },

    showDeepThinkingContainer() {
        const messagesArea = document.getElementById('messagesArea');
        if (!messagesArea) return null;

        // Always create fresh container
        const container = document.createElement('div');
        container.className = 'deep-thinking-container';
        container.id = this._uniqueId('cotContainer');
        container.innerHTML = `
            <div class="deep-thinking-header">
                <span class="deep-thinking-icon">🧠</span>
                <span class="deep-thinking-title">深度思考过程</span>
                <span class="deep-thinking-phase" id="${this._uniqueId('cotPhase')}"></span>
            </div>
            <div class="deep-thinking-content" id="${this._uniqueId('cotSteps')}"></div>
        `;

        const indicator = document.getElementById('typingIndicator');
        messagesArea.insertBefore(container, indicator);

        this._cotContainer = container;
        this._cotStep = 0;
        this._cotNextStepNeeded = false;
        this._thinkingBuffer = '';
        this._cotThinkingEl = null;
        this._createCotStep();

        container.scrollIntoView({ behavior: 'smooth', block: 'end' });
        return container;
    },

    _createCotStep() {
        this._cotStep++;
        const step = this._cotStep;
        const uid = this._uniqueId;

        const stepsContainer = document.getElementById(this._uniqueId('cotSteps'));
        if (!stepsContainer) return;

        const stepDiv = document.createElement('div');
        stepDiv.className = 'cot-step';
        stepDiv.innerHTML = `
            <div class="cot-step-header" onclick="ChatView._toggleCotStep(${step})">
                <span class="cot-step-number">步骤 ${step}</span>
                <span class="cot-step-status" id="${this._uniqueId('cot-status-' + step)}">💭 思考中</span>
                <span class="cot-step-toggle" id="${this._uniqueId('cot-toggle-' + step)}">▼</span>
            </div>
            <div class="cot-step-body" id="${this._uniqueId('cot-body-' + step)}">
                <div class="cot-step-thinking" id="${this._uniqueId('cot-think-' + step)}"></div>
                <div class="cot-step-tool" id="${this._uniqueId('cot-tool-' + step)}" style="display: none;">
                    <div class="cot-tool-header">
                        <span class="cot-tool-icon">🔧</span>
                        <span class="cot-tool-name" id="${this._uniqueId('cot-tool-name-' + step)}"></span>
                    </div>
                    <div class="cot-tool-args" id="${this._uniqueId('cot-tool-args-' + step)}"></div>
                </div>
                <div class="cot-step-observation" id="${this._uniqueId('cot-obs-' + step)}" style="display: none;">
                    <div class="cot-obs-header">👀 观察结果</div>
                    <div class="cot-obs-content" id="${this._uniqueId('cot-obs-content-' + step)}"></div>
                </div>
            </div>
        `;
        stepsContainer.appendChild(stepDiv);

        this._thinkingBuffer = '';
        this._cotThinkingEl = document.getElementById(this._uniqueId('cot-think-' + step));

        stepDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    },

    _toggleCotStep(step) {
        const body = document.getElementById(this._uniqueId('cot-body-' + step));
        const toggle = document.getElementById(this._uniqueId('cot-toggle-' + step));
        if (body && toggle) {
            const isHidden = body.style.display === 'none';
            body.style.display = isHidden ? 'block' : 'none';
            toggle.textContent = isHidden ? '▼' : '▶';
        }
    },

    updateDeepThinkingContent(content) {
        if (!this._cotContainer) return;

        this._thinkingBuffer += content;
        if (this._cotThinkingEl) {
            this._cotThinkingEl.textContent = this._thinkingBuffer;
            this._cotThinkingEl.scrollTop = this._cotThinkingEl.scrollHeight;
        }

        this._cotContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    },

    updateThinkingPhase(phase) {
        if (!this._cotContainer) return;

        const phaseEl = document.getElementById(this._uniqueId('cotPhase'));
        if (phaseEl) {
            const phaseMap = {
                'thinking': '💭 思考中...',
                'tool-call': '🔧 调用工具...',
                'observation': '👀 观察结果...',
                'summarizing': '📝 总结中...',
                'complete': '✅ 思考完成'
            };
            phaseEl.textContent = phaseMap[phase] || phase;
        }

        // Update current step status
        const statusEl = document.getElementById(this._uniqueId('cot-status-' + this._cotStep));
        if (statusEl) {
            const statusMap = {
                'thinking': '💭 思考中',
                'tool-call': '🔧 调用工具',
                'observation': '👀 观察结果',
                'summarizing': '📝 总结中',
                'complete': '✅ 完成'
            };
            statusEl.textContent = statusMap[phase] || phase;
        }

        // When entering "thinking" phase again, create a new step
        if (phase === 'thinking') {
            if (this._cotNextStepNeeded) {
                this._createCotStep();
            }
            this._cotNextStepNeeded = true;
        }

        // When complete, auto-collapse all steps except the last
        if (phase === 'complete') {
            for (let i = 1; i < this._cotStep; i++) {
                const body = document.getElementById(this._uniqueId('cot-body-' + i));
                const toggle = document.getElementById(this._uniqueId('cot-toggle-' + i));
                if (body && toggle && body.style.display !== 'none') {
                    body.style.display = 'none';
                    toggle.textContent = '▶';
                }
            }
        }
    },

    addThinkingToolCall(toolName, toolArgs) {
        if (!this._cotContainer) return;
        const step = this._cotStep;

        const toolDiv = document.getElementById(this._uniqueId('cot-tool-' + step));
        const toolNameEl = document.getElementById(this._uniqueId('cot-tool-name-' + step));
        const toolArgsEl = document.getElementById(this._uniqueId('cot-tool-args-' + step));

        if (toolDiv) toolDiv.style.display = 'block';
        if (toolNameEl) toolNameEl.textContent = toolName;
        if (toolArgsEl) {
            const argsStr = typeof toolArgs === 'object'
                ? JSON.stringify(toolArgs, null, 2) : String(toolArgs);
            if (argsStr && argsStr !== '{}') {
                toolArgsEl.innerHTML = `<pre>${this.escapeHtml(argsStr)}</pre>`;
            }
        }
        this._cotContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    },

    updateThinkingToolResult(result) {
        if (!this._cotContainer) return;
        const step = this._cotStep;

        const obsDiv = document.getElementById(this._uniqueId('cot-obs-' + step));
        const obsContent = document.getElementById(this._uniqueId('cot-obs-content-' + step));

        if (obsDiv) obsDiv.style.display = 'block';
        if (obsContent && result) {
            let content;
            if (typeof result === 'string') {
                content = result;
            } else {
                try { content = JSON.stringify(result, null, 2); }
                catch { content = String(result); }
            }
            const truncated = content.length > 500 ? content.substring(0, 500) + '...' : content;
            obsContent.innerHTML = `<div class="cot-obs-text">${this.escapeHtml(truncated)}</div>`;
        }
        this._cotContainer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    },

    // ═══════════════════════════════════════
    // Planning card (plan/react modes)
    // ═══════════════════════════════════════

    showPlanningCard(plan) {
        const messagesArea = document.getElementById('messagesArea');
        if (!messagesArea) return;

        const card = document.createElement('div');
        card.className = 'planning-card';

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
                    <div class="planning-steps-container"></div>
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
        const container = document.querySelector('.planning-steps-container:last-of-type');
        if (!container) return;

        // Extract a human-readable description from arguments
        let argPreview = '';
        const args = step.arguments || {};
        if (args.query) {
            argPreview = this.escapeHtml(String(args.query).substring(0, 80));
        } else if (args.file_name || args.filename) {
            argPreview = this.escapeHtml(String(args.file_name || args.filename));
        } else if (Object.keys(args).length > 0) {
            argPreview = this.escapeHtml(JSON.stringify(args).substring(0, 80));
        }

        const stepDiv = document.createElement('div');
        stepDiv.className = 'planning-step-item';
        stepDiv.innerHTML = `
            <div class="planning-step-main">
                <span class="planning-step-number">${stepNumber}.</span>
                <span class="planning-step-tool">${step.tool_name || step.tool || 'Unknown'}</span>
                ${argPreview ? `<span class="planning-step-query">${argPreview}</span>` : ''}
                <span class="planning-step-status running" id="pstep-status-${this._roundId}-${step.step_id}">⏳ 执行中</span>
            </div>
            <div class="planning-step-result" id="pstep-result-${this._roundId}-${step.step_id}"></div>
        `;
        container.appendChild(stepDiv);
        stepDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });
    },

    updateStepStatus(stepId, status, text) {
        const el = document.getElementById(`pstep-status-${this._roundId}-${stepId}`);
        if (el) { el.className = `planning-step-status ${status}`; el.textContent = text; }
    },

    updateStepResult(stepId, result) {
        const el = document.getElementById(`pstep-result-${this._roundId}-${stepId}`);
        if (el && result) {
            const content = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
            const truncated = content.substring(0, 300);
            el.innerHTML = `<div class="step-result-inline">${this._renderMarkdown(truncated)}${content.length > 300 ? '...' : ''}</div>`;
        }
    },

    // ═══════════════════════════════════════
    // UI helpers
    // ═══════════════════════════════════════

    renderSessions(sessions) {
        const list = document.getElementById('sessionsList');
        if (!list) return;

        if (!sessions || sessions.length === 0) {
            list.innerHTML = `<div class="empty-state"><div class="icon">📝</div><h3>暂无会话</h3></div>`;
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
            </div>`;
        }).join('');
    },

    renderAgentSelector(agents) {
        const selector = document.getElementById('agentSelector');
        if (!selector) return;
        const currentAgentId = AppState.get('currentAgentId');
        selector.innerHTML = `<option value="">默认（自动选择）</option>` +
            agents.map(a => `<option value="${a.id}" ${a.id === currentAgentId ? 'selected' : ''}>${this.escapeHtml(a.name)} (${a.type})</option>`).join('');
    },

    renderActiveAgentInfo(agent) {
        const info = document.getElementById('activeAgentInfo');
        if (!info) return;
        if (!agent) {
            info.innerHTML = '<div style="font-size: 13px; color: var(--text-muted);">使用默认Agent</div>';
            this._updateThinkingToggle('direct');
            return;
        }
        const modeIcons = { 'plan': '📋', 'react': '🔄', 'react_cot': '🧠', 'direct': '⚡' };
        const modeIcon = modeIcons[agent.execution_mode] || '📋';
        const modeNames = { 'plan': 'Plan', 'react': 'ReAct', 'react_cot': 'COT', 'direct': 'Direct' };
        const modeName = modeNames[agent.execution_mode] || agent.execution_mode;
        info.innerHTML = `<div style="display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px; background: rgba(102, 126, 234, 0.2); border-radius: 16px; font-size: 13px;"><span>${modeIcon}</span><span style="font-weight: 500;">${this.escapeHtml(agent.name)}</span><span style="color: var(--text-secondary);">(${modeName})</span></div>`;
        this._updateThinkingToggle(agent.execution_mode);
    },

    _updateThinkingToggle(executionMode) {
        const row = document.getElementById('deepThinkingRow');
        const checkbox = document.getElementById('deepThinkingCheckbox');
        if (!row || !checkbox) return;

        // Only show toggle in direct mode; plan/react/react_cot always use deep thinking
        if (executionMode === 'direct') {
            row.style.display = 'flex';
            // Default off for direct mode
            checkbox.checked = false;
        } else {
            row.style.display = 'none';
            checkbox.checked = true;
        }
    },

    hideAgentSelector() {
        const c = document.getElementById('agentSelector')?.parentElement;
        if (c) c.innerHTML = `<span style="font-size: 14px; color: var(--text-secondary);">Agent:</span><span style="font-weight: 500; color: var(--primary);">已锁定</span>`;
        const btn = document.querySelector('.chat-header .btn.btn-secondary');
        if (btn) btn.style.display = 'none';
    },

    updateConnectionStatus(status, text) {
        const d = document.getElementById('connectionStatus');
        const dot = document.getElementById('statusDot');
        const t = document.getElementById('statusText');
        if (d) d.className = `connection-status ${status}`;
        if (dot) dot.className = `status-dot ${status}`;
        if (t) t.textContent = text;
    },

    setInputsEnabled(enabled) {
        // Called on WS connect/disconnect
        const input = document.getElementById('messageInput');
        const sendBtn = document.getElementById('sendButton');
        // Only enable if AI is not responding
        const canEnable = enabled && !this._aiResponding;
        if (input) input.disabled = !canEnable;
        if (sendBtn) sendBtn.disabled = !canEnable;
        if (canEnable && input) input.focus();
    },

    showTypingIndicator(show) {
        const indicator = document.getElementById('typingIndicator');
        if (indicator) {
            indicator.style.display = show ? 'flex' : 'none';
            if (show) indicator.scrollIntoView({ behavior: 'smooth', block: 'end' });
        }
    },

    _clearEmptyState() {
        const empty = document.getElementById('emptyState');
        if (empty) empty.remove();
    },

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
        this._resetRoundState();
        this.messageCount = 0;
    },

    showLoadMoreButton() {
        // Remove existing button if any
        this.hideLoadMoreButton();

        const messagesArea = document.getElementById('messagesArea');
        if (!messagesArea) return;

        const btn = document.createElement('div');
        btn.id = 'loadMoreBtn';
        btn.style.cssText = 'text-align: center; padding: 10px; margin: 8px 0;';
        btn.innerHTML = `<button class="btn btn-secondary" style="font-size: 13px; padding: 6px 20px;" onclick="ChatModule.loadMoreHistory()">⬆ 加载更早的消息</button>`;

        const firstMsg = messagesArea.querySelector('.message');
        if (firstMsg) {
            messagesArea.insertBefore(btn, firstMsg);
        } else {
            const indicator = document.getElementById('typingIndicator');
            messagesArea.insertBefore(btn, indicator);
        }
    },

    hideLoadMoreButton() {
        const btn = document.getElementById('loadMoreBtn');
        if (btn) btn.remove();
    },

    prependMessages(messages) {
        const messagesArea = document.getElementById('messagesArea');
        if (!messagesArea) return;

        // Remove load more button temporarily
        const loadMoreBtn = document.getElementById('loadMoreBtn');
        if (loadMoreBtn) loadMoreBtn.remove();

        // Create a document fragment with the older messages
        const fragment = document.createDocumentFragment();
        messages.forEach(msg => {
            const sender = msg.role === 'assistant' ? 'ai' : msg.role;
            const timeStr = msg.created_at
                ? new Date(msg.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
                : new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });

            const avatarIcon = sender === 'user' ? '👤' : '🤖';
            const avatarClass = sender === 'user' ? 'user' : 'ai';
            const renderedContent = sender === 'ai' ? this._renderMarkdown(msg.content) : this.escapeHtml(msg.content);

            const messageDiv = document.createElement('div');
            messageDiv.className = 'message';
            messageDiv.innerHTML = `
                <div class="message-header">
                    <span class="message-avatar ${avatarClass}">${avatarIcon}</span>
                    <span class="message-sender">${sender === 'user' ? '我' : 'AI'}</span>
                    <span class="message-time">${timeStr}</span>
                </div>
                <div class="message-content">${renderedContent}</div>
            `;
            fragment.appendChild(messageDiv);
        });

        // Insert before the first existing message
        const firstMsg = messagesArea.querySelector('.message');
        if (firstMsg) {
            messagesArea.insertBefore(fragment, firstMsg);
        } else {
            const indicator = document.getElementById('typingIndicator');
            messagesArea.insertBefore(fragment, indicator);
        }
    }
};

// ═══════════════════════════════════════
// Styles
// ═══════════════════════════════════════
const chatStyles = document.createElement('style');
chatStyles.textContent = `
    .connection-status { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; padding: 4px 12px; border-radius: 20px; }
    .connection-status.connected { background: var(--success-bg); color: var(--success-color); }
    .connection-status.disconnected { background: var(--error-bg); color: var(--error-color); }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; }
    .status-dot.connected { background: #4caf50; }
    .status-dot.disconnected { background: #dc3545; }

    .deep-thinking-container { background: #f8f9fa; border-left: 4px solid var(--primary); border-radius: 8px; margin: 16px 0; overflow: hidden; }
    .deep-thinking-header { display: flex; align-items: center; gap: 8px; padding: 12px 16px; background: rgba(102, 126, 234, 0.1); border-bottom: 1px solid var(--border-color); }
    .deep-thinking-icon { font-size: 18px; }
    .deep-thinking-title { font-weight: 600; color: #333; font-size: 14px; }
    .deep-thinking-phase { margin-left: auto; font-size: 12px; color: #666; padding: 2px 10px; background: rgba(102, 126, 234, 0.08); border-radius: 12px; }
    .deep-thinking-content { padding: 0; }

    .cot-step { border-bottom: 1px solid #eee; }
    .cot-step:last-child { border-bottom: none; }
    .cot-step-header { display: flex; align-items: center; gap: 8px; padding: 10px 16px; background: rgba(102, 126, 234, 0.04); cursor: pointer; user-select: none; }
    .cot-step-header:hover { background: rgba(102, 126, 234, 0.08); }
    .cot-step-number { font-size: 12px; font-weight: 600; color: var(--primary); padding: 2px 8px; background: rgba(102, 126, 234, 0.12); border-radius: 10px; }
    .cot-step-status { font-size: 12px; color: #666; }
    .cot-step-toggle { margin-left: auto; font-size: 10px; color: #999; }
    .cot-step-body { padding: 0 16px 12px 16px; }

    .cot-step-thinking { font-size: 13px; color: #555; line-height: 1.7; white-space: pre-wrap; max-height: 200px; overflow-y: auto; padding: 8px 0; border-bottom: 1px dashed #e8e8e8; }
    .cot-step-tool { padding: 8px 0; }
    .cot-tool-header { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
    .cot-tool-icon { font-size: 14px; }
    .cot-tool-name { font-size: 13px; font-weight: 500; color: var(--primary); }
    .cot-tool-args { font-size: 12px; color: #666; background: #fafafa; border-radius: 6px; padding: 6px 10px; }
    .cot-tool-args pre { margin: 0; white-space: pre-wrap; word-break: break-all; }
    .cot-step-observation { padding: 8px 0; }
    .cot-obs-header { font-size: 12px; color: #888; margin-bottom: 4px; }
    .cot-obs-text { font-size: 12px; color: #666; white-space: pre-wrap; word-break: break-all; max-height: 150px; overflow-y: auto; background: #fafafa; border-radius: 6px; padding: 6px 10px; }

    .message-content h1 { font-size: 1.4em; margin: 12px 0 8px; font-weight: 700; border-bottom: 2px solid #e0e0e0; padding-bottom: 4px; }
    .message-content h2 { font-size: 1.25em; margin: 10px 0 6px; font-weight: 700; border-bottom: 1px solid #eee; padding-bottom: 3px; }
    .message-content h3 { font-size: 1.1em; margin: 8px 0 4px; font-weight: 600; }
    .message-content h4 { font-size: 1em; margin: 6px 0 4px; font-weight: 600; }
    .message-content p { margin: 6px 0; line-height: 1.7; }
    .message-content ul, .message-content ol { margin: 6px 0; padding-left: 24px; }
    .message-content li { margin: 3px 0; line-height: 1.6; }
    .message-content strong { font-weight: 600; }
    .message-content em { font-style: italic; }
    .message-content code { background: #f0f0f0; padding: 1px 5px; border-radius: 3px; font-size: 0.9em; font-family: 'Consolas', 'Monaco', monospace; }
    .message-content pre { background: #2d2d2d; color: #f8f8f2; padding: 12px 16px; border-radius: 8px; overflow-x: auto; margin: 8px 0; }
    .message-content pre code { background: none; padding: 0; color: inherit; font-size: 0.9em; }
    .message-content blockquote { border-left: 3px solid var(--primary); margin: 8px 0; padding: 4px 12px; color: #666; background: #f8f9fa; border-radius: 0 6px 6px 0; }
    .message-content table { border-collapse: collapse; margin: 8px 0; width: 100%; }
    .message-content th, .message-content td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; }
    .message-content th { background: #f5f5f5; font-weight: 600; }
    .message-content a { color: var(--primary); text-decoration: none; }
    .message-content a:hover { text-decoration: underline; }
    .message-content hr { border: none; border-top: 1px solid #e0e0e0; margin: 12px 0; }

    .planning-card { background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%); border: 1px solid #d1d5db; border-radius: 10px; padding: 15px; margin: 10px 0; }
    .planning-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
    .planning-badges { display: flex; gap: 8px; }
    .planning-badge { font-size: 11px; padding: 3px 8px; border-radius: 10px; font-weight: 500; }
    .planning-badge.complexity { background: #e3f2fd; color: #1565c0; }
    .planning-badge.strategy { background: #f3e5f5; color: #7b1fa2; }
    .planning-description { font-size: 13px; color: #666; margin: 8px 0; padding: 8px 10px; background: rgba(255,255,255,0.7); border-radius: 6px; border-left: 3px solid var(--primary); }
    .planning-steps-title { font-size: 13px; font-weight: 600; color: #333; margin-bottom: 8px; }
    .planning-step-item { background: white; padding: 10px 12px; margin: 6px 0; border-radius: 8px; border-left: 3px solid var(--primary); }
    .planning-step-main { display: flex; align-items: center; gap: 10px; }
    .planning-step-number { font-weight: 600; color: var(--primary); }
    .planning-step-tool { color: #333; font-weight: 500; }
    .planning-step-query { color: var(--text-secondary); font-size: 12px; margin-left: 4px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .planning-step-status { margin-left: auto; font-size: 12px; }
    .planning-step-status.running { color: #f57c00; }
    .planning-step-status.complete { color: #388e3c; }
    .planning-step-status.error { color: #d32f2f; }
    .planning-step-args { font-size: 12px; color: #666; margin-top: 6px; background: #f8f9fa; padding: 6px; border-radius: 4px; white-space: pre-wrap; }
    .planning-step-result { margin-top: 6px; }
    .step-result-inline { font-size: 12px; color: #666; white-space: pre-wrap; }
    .planning-no-steps { margin-top: 12px; padding: 8px 12px; background: #e8f5e9; border-radius: 6px; display: flex; align-items: center; gap: 8px; }

    .deep-thinking-toggle-row { display: flex; align-items: center; gap: 8px; }
    .deep-thinking-switch { position: relative; display: inline-block; width: 36px; height: 20px; cursor: pointer; }
    .deep-thinking-switch input { opacity: 0; width: 0; height: 0; }
    .deep-thinking-slider { position: absolute; inset: 0; background: #ccc; border-radius: 20px; transition: 0.2s; }
    .deep-thinking-slider::before { content: ''; position: absolute; height: 16px; width: 16px; left: 2px; bottom: 2px; background: white; border-radius: 50%; transition: 0.2s; }
    .deep-thinking-switch input:checked + .deep-thinking-slider { background: var(--primary); }
    .deep-thinking-switch input:checked + .deep-thinking-slider::before { transform: translateX(16px); }
    .deep-thinking-label { font-size: 12px; color: var(--text-secondary); user-select: none; cursor: pointer; }

    .typing-indicator { display: flex; align-items: center; gap: 5px; color: #999; padding: 0 40px; }
    .typing-dots { display: flex; gap: 3px; }
    .typing-dot { width: 6px; height: 6px; background: #999; border-radius: 50%; animation: typingBounce 1.4s infinite; }
    .typing-dot:nth-child(2) { animation-delay: 0.2s; }
    .typing-dot:nth-child(3) { animation-delay: 0.4s; }
    @keyframes typingBounce { 0%, 60%, 100% { transform: translateY(0); } 30% { transform: translateY(-6px); } }
`;
document.head.appendChild(chatStyles);
