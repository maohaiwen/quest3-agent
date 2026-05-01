// Agent Module
const AgentModule = {
    name: 'agent',
    agents: [],
    mcpServers: [],
    availableTools: [],
    currentEditId: null,
    currentStep: 1,
    selectedMode: null,
    isEditMode: false,

    init() {
        this.loadAgents();
        this.loadMCPServers();
        this.loadTools();
    },

    render(container) {
        AgentView.render(container);
    },

    destroy() {
        this.currentEditId = null;
        this.currentStep = 1;
        this.selectedMode = null;
        this.isEditMode = false;
    },

    async loadAgents() {
        try {
            const data = await API.get('/api/agents');
            this.agents = data.agents || [];
            AgentView.renderAgents(this.agents);
        } catch (error) {
            console.error('Failed to load agents:', error);
            Toast.error('加载Agent列表失败');
        }
    },

    async loadMCPServers() {
        try {
            const data = await API.get('/api/mcp/servers');
            this.mcpServers = data.servers || [];
        } catch (error) {
            console.error('Failed to load MCP servers:', error);
        }
    },

    async loadTools() {
        try {
            const data = await API.get('/tools');
            this.availableTools = data.tools || [];
        } catch (error) {
            console.error('Failed to load tools:', error);
        }
    },

    openCreateModal() {
        this.currentEditId = null;
        this.selectedMode = null;
        this.currentStep = 1;
        this.isEditMode = false;
        this.showModal({
            title: '新建Agent',
            agent: null
        });
    },

    async editAgent(agentId) {
        const agent = this.agents.find(a => a.id === agentId);
        if (!agent) return;

        this.currentEditId = agentId;
        this.selectedMode = agent.execution_mode || 'plan';
        this.currentStep = 2;
        this.isEditMode = true;
        this.showModal({
            title: '编辑Agent',
            agent: agent
        });
    },

    showModal({ title, agent }) {
        Modal.show({
            title,
            content: this.buildModalContent(agent),
            footer: this.buildModalFooter(),
            width: '750px',
            onShow: () => this.onModalShow(agent)
        });
    },

    buildModalContent(agent) {
        return `
            <div id="agentMessageContainer"></div>

            <!-- Step Indicator -->
            <div class="step-indicator" id="agentStepIndicator">
                <div class="step-item active" id="agentStep1">
                    <div class="step-number">1</div>
                    <div class="step-label">选择模式</div>
                </div>
                <div class="step-item" id="agentStep2">
                    <div class="step-number">2</div>
                    <div class="step-label">配置信息</div>
                </div>
            </div>

            <!-- Step 1: Mode Selection -->
            <div id="agentStepContent1">
                <div class="form-section">
                    <h3>选择执行模式</h3>
                    <p style="color: #666; font-size: 13px; margin-bottom: 15px;">
                        这决定了Agent的工作方式，创建后也可以随时修改
                    </p>

                    <div class="mode-cards">
                        <div class="mode-card" data-mode="plan" onclick="AgentModule.selectMode('plan')">
                            <div class="mode-icon">📋</div>
                            <div class="mode-name">Plan模式</div>
                            <div class="mode-description">
                                先规划完整的执行步骤，再按步骤执行。适合复杂、多步骤的任务。
                            </div>
                            <div class="mode-note tools">
                                🔧 需要配置工具
                            </div>
                        </div>

                        <div class="mode-card" data-mode="react" onclick="AgentModule.selectMode('react')">
                            <div class="mode-icon">🔄</div>
                            <div class="mode-name">ReAct模式</div>
                            <div class="mode-description">
                                通过思考-行动-观察的循环逐步执行。适合需要边做边调整的任务。
                            </div>
                            <div class="mode-note tools">
                                🔧 需要配置工具
                            </div>
                        </div>

                        <div class="mode-card" data-mode="direct" onclick="AgentModule.selectMode('direct')">
                            <div class="mode-icon">⚡</div>
                            <div class="mode-name">Direct模式</div>
                            <div class="mode-description">
                                直接调用LLM生成回复，不使用工具。适合简单问答、日常聊天。
                            </div>
                            <div class="mode-note no-tools">
                                💬 不需要工具
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Step 2: Configuration -->
            <div id="agentStepContent2" style="display: none;">
                <form id="agentForm">
                    <input type="hidden" id="agentId">

                    <div class="form-section">
                        <h3>基本信息</h3>

                        <div class="form-group">
                            <label>名称 *</label>
                            <input type="text" class="form-control" id="agentName" required
                                   placeholder="例如: Python代码助手">
                        </div>

                        <div class="form-group">
                            <label>描述</label>
                            <input type="text" class="form-control" id="agentDescription"
                                   placeholder="简要描述Agent的功能">
                        </div>

                        <div class="form-group">
                            <label>类型</label>
                            <select class="form-control" id="agentType">
                                <option value="chat">💬 聊天助手</option>
                                <option value="coder">💻 代码助手</option>
                                <option value="researcher">📊 研究助手</option>
                                <option value="custom">⚙️ 自定义</option>
                            </select>
                        </div>

                        <div class="form-group">
                            <label>优先级</label>
                            <input type="number" class="form-control" id="agentPriority" min="0" value="0"
                                   placeholder="数字越高优先级越高">
                        </div>

                        <div class="form-group checkbox-group">
                            <input type="checkbox" id="agentEnabled" checked>
                            <label for="agentEnabled">启用</label>
                        </div>
                    </div>

                    <!-- Tool/MCP Section - only show for plan/react -->
                    <div class="form-section" id="agentToolsMcpSection">
                        <h3>🔧 工具配置</h3>

                        <div class="form-group">
                            <label>MCP服务器</label>
                            <div id="agentMcpServerList" class="checkbox-list">
                            </div>
                        </div>

                        <div class="form-group">
                            <label>本地工具</label>
                            <div id="agentToolsList" class="checkbox-list">
                            </div>
                        </div>
                    </div>

                    <div class="form-section">
                        <h3>LLM参数（可选，将使用全局默认值）</h3>

                        <div class="form-group">
                            <label>模型</label>
                            <input type="text" class="form-control" id="agentModel"
                                   placeholder="例如: claude-3-5-sonnet-20241022">
                        </div>

                        <div class="form-group">
                            <label>温度</label>
                            <input type="number" class="form-control" id="agentTemperature" min="0" max="1" step="0.1"
                                   placeholder="0.0-1.0">
                        </div>

                        <div class="form-group">
                            <label>最大Token数</label>
                            <input type="number" class="form-control" id="agentMaxTokens" min="1"
                                   placeholder="例如: 4096">
                        </div>
                    </div>

                    <div class="form-section">
                        <h3>系统提示词</h3>

                        <div class="form-group">
                            <textarea class="form-control" id="agentSystemPrompt" rows="5"
                                      placeholder="定义Agent的角色和行为..."></textarea>
                            <div style="display: flex; gap: 10px; margin-top: 8px;">
                                <button type="button" class="btn btn-secondary" onclick="AgentModule.loadTemplate()">📋 使用模板</button>
                                <button type="button" class="btn btn-secondary" onclick="AgentModule.resetSystemPrompt()">↺ 重置为默认</button>
                            </div>
                        </div>
                    </div>
                </form>
            </div>
        `;
    },

    buildModalFooter() {
        if (this.isEditMode) {
            return `
                <button class="btn btn-secondary" onclick="Modal.close()">取消</button>
                <button class="btn btn-primary" onclick="AgentModule.saveAgent()">保存</button>
            `;
        }
        return `
            <button class="btn btn-secondary" onclick="Modal.close()">取消</button>
            <button class="btn btn-primary" id="agentNextStepBtn" onclick="AgentModule.goToStep2()" disabled>下一步</button>
        `;
    },

    onModalShow(agent) {
        // Render checkboxes
        this.renderMCPCheckboxes();
        this.renderToolCheckboxes();

        if (this.isEditMode && agent) {
            this.fillFormForEdit(agent);
        } else {
            this.resetFormForCreate();
        }
    },

    renderMCPCheckboxes() {
        const container = document.getElementById('agentMcpServerList');
        if (!container) return;

        if (!this.mcpServers || this.mcpServers.length === 0) {
            container.innerHTML = '<small style="color: #999;">没有可用的MCP服务器</small>';
            return;
        }

        container.innerHTML = this.mcpServers.map(server => `
            <div class="checkbox-item">
                <input type="checkbox" id="agent_mcp_${server.id}" value="${server.id}">
                <label for="agent_mcp_${server.id}">
                    <strong>${this.escapeHtml(server.name)}</strong>
                    <small style="color: #999; margin-left: 5px;">(${server.status || 'unknown'})</small>
                </label>
            </div>
        `).join('');
    },

    renderToolCheckboxes() {
        const container = document.getElementById('agentToolsList');
        if (!container) return;

        if (!this.availableTools || this.availableTools.length === 0) {
            container.innerHTML = '<small style="color: #999;">没有可用的本地工具</small>';
            return;
        }

        container.innerHTML = this.availableTools.map(tool => `
            <div class="checkbox-item">
                <input type="checkbox" id="agent_tool_${tool.name}" value="${tool.name}">
                <label for="agent_tool_${tool.name}">
                    <strong>${this.escapeHtml(tool.name)}</strong>
                    <small style="color: #999; margin-left: 5px;">(${tool.source || 'local'})</small>
                </label>
            </div>
        `).join('');
    },

    resetFormForCreate() {
        // Reset step indicator
        document.getElementById('agentStep1').classList.add('active');
        document.getElementById('agentStep1').classList.remove('completed');
        document.getElementById('agentStep2').classList.remove('active');

        // Show step 1
        document.getElementById('agentStepContent1').style.display = 'block';
        document.getElementById('agentStepContent2').style.display = 'none';
    },

    fillFormForEdit(agent) {
        // Update step indicator - skip step 1 for edit
        document.getElementById('agentStep1').classList.remove('active');
        document.getElementById('agentStep1').classList.add('completed');
        document.getElementById('agentStep2').classList.add('active');

        // Update mode selection UI
        document.querySelectorAll('.mode-card').forEach(card => {
            card.classList.remove('selected');
            if (card.dataset.mode === this.selectedMode) {
                card.classList.add('selected');
            }
        });

        // Fill form values
        document.getElementById('agentId').value = agent.id;
        document.getElementById('agentName').value = agent.name || '';
        document.getElementById('agentDescription').value = agent.description || '';
        document.getElementById('agentType').value = agent.type || 'chat';
        document.getElementById('agentPriority').value = agent.priority || 0;
        document.getElementById('agentEnabled').checked = agent.enabled;
        document.getElementById('agentModel').value = agent.model || '';
        document.getElementById('agentTemperature').value = agent.temperature || '';
        document.getElementById('agentMaxTokens').value = agent.max_tokens || '';
        document.getElementById('agentSystemPrompt').value = agent.system_prompt || '';

        // Check MCP servers
        document.querySelectorAll('#agentMcpServerList input[type="checkbox"]').forEach(cb => {
            cb.checked = (agent.mcp_servers || []).some(mcp => mcp.server_id === cb.value);
        });

        // Check tools
        document.querySelectorAll('#agentToolsList input[type="checkbox"]').forEach(cb => {
            cb.checked = (agent.tools || []).includes(cb.value);
        });

        // Show step 2
        document.getElementById('agentStepContent1').style.display = 'none';
        document.getElementById('agentStepContent2').style.display = 'block';
        this.updateToolsSectionVisibility();

        // Update footer
        this.updateFooter();
    },

    selectMode(mode) {
        this.selectedMode = mode;

        // Update UI
        document.querySelectorAll('.mode-card').forEach(card => {
            card.classList.remove('selected');
            if (card.dataset.mode === mode) {
                card.classList.add('selected');
            }
        });

        // Enable next button
        const nextBtn = document.getElementById('agentNextStepBtn');
        if (nextBtn) {
            nextBtn.disabled = false;
        }
    },

    goToStep2() {
        if (!this.selectedMode) {
            this.showMessage('请先选择执行模式', 'error');
            return;
        }

        this.currentStep = 2;

        // Update step indicator
        document.getElementById('agentStep1').classList.remove('active');
        document.getElementById('agentStep1').classList.add('completed');
        document.getElementById('agentStep2').classList.add('active');

        // Show/hide content
        document.getElementById('agentStepContent1').style.display = 'none';
        document.getElementById('agentStepContent2').style.display = 'block';

        // Update footer
        this.updateFooter();

        // Show/hide tools section based on mode
        this.updateToolsSectionVisibility();

        // Load template based on type
        this.loadTemplate();
    },

    goToStep1() {
        this.currentStep = 1;

        // Update step indicator
        document.getElementById('agentStep1').classList.add('active');
        document.getElementById('agentStep1').classList.remove('completed');
        document.getElementById('agentStep2').classList.remove('active');

        // Show/hide content
        document.getElementById('agentStepContent1').style.display = 'block';
        document.getElementById('agentStepContent2').style.display = 'none';

        // Update footer
        this.updateFooter();
    },

    updateFooter() {
        const footer = document.querySelector('.modal-footer');
        if (!footer) return;

        if (this.isEditMode) {
            footer.innerHTML = `
                <button class="btn btn-secondary" onclick="Modal.close()">取消</button>
                <button class="btn btn-primary" onclick="AgentModule.saveAgent()">保存</button>
            `;
        } else if (this.currentStep === 1) {
            footer.innerHTML = `
                <button class="btn btn-secondary" onclick="Modal.close()">取消</button>
                <button class="btn btn-primary" id="agentNextStepBtn" onclick="AgentModule.goToStep2()" ${!this.selectedMode ? 'disabled' : ''}>下一步</button>
            `;
        } else {
            footer.innerHTML = `
                <button class="btn btn-secondary" onclick="AgentModule.goToStep1()">上一步</button>
                <button class="btn btn-secondary" onclick="Modal.close()">取消</button>
                <button class="btn btn-primary" onclick="AgentModule.saveAgent()">创建</button>
            `;
        }
    },

    updateToolsSectionVisibility() {
        const section = document.getElementById('agentToolsMcpSection');
        if (!section) return;

        if (this.selectedMode === 'direct') {
            section.style.display = 'none';
        } else {
            section.style.display = 'block';
        }
    },

    loadTemplate() {
        const type = document.getElementById('agentType')?.value || 'chat';
        const templates = {
            'chat': '你是一个友好的聊天助手，能够进行自然的对话交流。请用清晰、简洁的语言回答问题。',
            'coder': '你是一个专业的编程助手，擅长多种编程语言（尤其是Python）。你能够帮助用户编写、调试和优化代码。在提供代码时，请添加适当的注释。',
            'researcher': '你是一个研究助手，擅长信息收集、分析和总结。你能够帮助用户查找资料、分析数据并提供建议。请确保你的回答准确、有据可查。',
            'custom': '请根据你的角色定义来帮助用户完成任务。'
        };

        const textarea = document.getElementById('agentSystemPrompt');
        if (textarea && !textarea.value) {
            textarea.value = templates[type] || templates['custom'];
        }
    },

    resetSystemPrompt() {
        this.loadTemplate();
    },

    async saveAgent() {
        const name = document.getElementById('agentName')?.value?.trim();
        if (!name) {
            this.showMessage('请填写名称', 'error');
            return;
        }

        const formData = {
            name: name,
            description: document.getElementById('agentDescription')?.value?.trim(),
            type: document.getElementById('agentType')?.value,
            priority: parseInt(document.getElementById('agentPriority')?.value) || 0,
            enabled: document.getElementById('agentEnabled')?.checked,
            execution_mode: this.selectedMode,
            model: document.getElementById('agentModel')?.value?.trim() || null,
            temperature: parseFloat(document.getElementById('agentTemperature')?.value) || null,
            max_tokens: parseInt(document.getElementById('agentMaxTokens')?.value) || null,
            system_prompt: document.getElementById('agentSystemPrompt')?.value?.trim() || '',
            mcp_servers: [],
            tools: []
        };

        // Only collect tools if not in direct mode
        if (this.selectedMode !== 'direct') {
            document.querySelectorAll('#agentMcpServerList input[type="checkbox"]:checked').forEach(cb => {
                formData.mcp_servers.push(cb.value);
            });

            document.querySelectorAll('#agentToolsList input[type="checkbox"]:checked').forEach(cb => {
                formData.tools.push(cb.value);
            });
        }

        try {
            if (this.currentEditId) {
                await API.put(`/api/agents/${this.currentEditId}`, formData);
                Toast.success('Agent更新成功');
            } else {
                await API.post('/api/agents', formData);
                Toast.success('Agent创建成功');
            }

            Modal.close();
            await this.loadAgents();

            // Update chat module agents if loaded
            const chatAgents = await API.get('/api/agents?enabled_only=true');
            AppState.set('agents', chatAgents.agents || []);

        } catch (error) {
            console.error('Failed to save agent:', error);
            Toast.error(error.message || '保存失败');
        }
    },

    async toggleAgent(agentId) {
        const agent = this.agents.find(a => a.id === agentId);
        if (!agent) return;

        try {
            await API.put(`/api/agents/${agentId}`, { enabled: !agent.enabled });
            Toast.success(agent.enabled ? 'Agent已禁用' : 'Agent已启用');
            await this.loadAgents();
        } catch (error) {
            console.error('Failed to toggle agent:', error);
            Toast.error('操作失败');
        }
    },

    async deleteAgent(agentId) {
        const agent = this.agents.find(a => a.id === agentId);
        if (!agent) return;

        if (!confirm(`确定要删除Agent "${agent.name}" 吗？\n此操作不可恢复。`)) {
            return;
        }

        try {
            await API.delete(`/api/agents/${agentId}`);
            Toast.success('Agent删除成功');
            await this.loadAgents();
        } catch (error) {
            console.error('Failed to delete agent:', error);
            Toast.error('删除失败');
        }
    },

    showMessage(message, type) {
        const container = document.getElementById('agentMessageContainer');
        if (!container) return;

        if (type === 'error') {
            container.innerHTML = `<div class="error-message">❌ ${this.escapeHtml(message)}</div>`;
        } else {
            container.innerHTML = `<div class="success-message">✅ ${this.escapeHtml(message)}</div>`;
        }
    },

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};
