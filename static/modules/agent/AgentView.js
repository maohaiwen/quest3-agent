// Agent View
const AgentView = {
    container: null,

    render(container) {
        this.container = container;
        container.innerHTML = `
            <div style="padding: 24px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
                    <h2 style="font-size: 20px; font-weight: 600;">🤖 Agent管理</h2>
                    <button class="btn btn-primary btn-lg" onclick="AgentModule.openCreateModal()">
                        ➕ 新建Agent
                    </button>
                </div>
                <div id="agentGrid" class="card-grid"></div>
            </div>
        `;
    },

    renderAgents(agents) {
        const grid = document.getElementById('agentGrid');
        if (!grid) return;

        if (!agents || agents.length === 0) {
            grid.innerHTML = `
                <div class="empty-state" style="grid-column: 1 / -1; text-align: center; padding: 60px 20px; color: #999;">
                    <div class="empty-state-icon" style="font-size: 64px; margin-bottom: 20px;">🤖</div>
                    <h3 style="font-size: 20px; margin-bottom: 10px; color: #666;">还没有创建Agent</h3>
                    <p style="color: #999; margin-bottom: 20px;">点击上方的"新建Agent"按钮来创建你的第一个智能助手</p>
                    <button class="btn btn-primary btn-lg" onclick="AgentModule.openCreateModal()">
                        ➕ 创建第一个Agent
                    </button>
                </div>
            `;
            return;
        }

        grid.innerHTML = agents.map(agent => `
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 12px;" onclick="window.location.href='/static/index.html#chat?agent_id=${agent.id}'">
                    <div>
                        <div style="font-size: 18px; font-weight: 600; color: #333;">${this.escapeHtml(agent.name)}</div>
                        <div style="margin-top: 6px; display: flex; gap: 6px; flex-wrap: wrap;">
                            <span class="badge" style="background: rgba(102, 126, 234, 0.1); color: #667eea;">
                                ${this.getTypeIcon(agent.type)} ${this.getTypeName(agent.type)}
                            </span>
                            <span class="badge" style="background: rgba(118, 75, 162, 0.1); color: #764ba2;">
                                ${this.getModeIcon(agent.execution_mode)} ${this.getModeName(agent.execution_mode)}
                            </span>
                            <span class="badge ${agent.enabled ? 'badge-success' : 'badge-error'}" style="${agent.enabled ? 'background: #d4edda; color: #155724;' : 'background: #fee; color: #dc3545;'}">
                                ${agent.enabled ? '✓ 启用' : '✗ 禁用'}
                            </span>
                        </div>
                    </div>
                </div>

                ${agent.description ? `<p style="color: #666; font-size: 14px; margin-bottom: 12px; cursor: pointer;" onclick="window.location.href='/static/index.html#chat?agent_id=${agent.id}'">${this.escapeHtml(agent.description)}</p>` : ''}

                <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-bottom: 12px; font-size: 13px; color: #777; cursor: pointer;" onclick="window.location.href='/static/index.html#chat?agent_id=${agent.id}'">
                    <div><span style="color: #999;">使用次数:</span> ${agent.usage_count || 0}</div>
                    <div><span style="color: #999;">优先级:</span> ${agent.priority || 0}</div>
                    <div><span style="color: #999;">创建时间:</span> ${this.formatDate(agent.created_at)}</div>
                </div>

                <div style="display: flex; gap: 8px; padding-top: 12px; border-top: 1px solid var(--border-color);">
                    <button class="btn btn-secondary" onclick="AgentModule.editAgent('${agent.id}')" style="flex: 1;">✏️ 编辑</button>
                    <button class="btn btn-secondary" onclick="AgentModule.toggleAgent('${agent.id}')" style="flex: 1;">
                        ${agent.enabled ? '✗ 禁用' : '✓ 启用'}
                    </button>
                    <button class="btn btn-danger" onclick="AgentModule.deleteAgent('${agent.id}')" style="flex: 1;">🗑️ 删除</button>
                </div>
            </div>
        `).join('');
    },

    renderMCPServers(servers) {
        // This is called when opening the modal to populate MCP server list
        return servers.map(server => `
            <div class="checkbox-item">
                <input type="checkbox" id="mcp_${server.id}" value="${server.id}">
                <label for="mcp_${server.id}">
                    <strong>${this.escapeHtml(server.name)}</strong>
                    <small style="color: #999; margin-left: 5px;">(${server.status || 'unknown'})</small>
                </label>
            </div>
        `).join('');
    },

    renderTools(tools) {
        return tools.map(tool => `
            <div class="checkbox-item">
                <input type="checkbox" id="tool_${tool.name}" value="${tool.name}">
                <label for="tool_${tool.name}">
                    <strong>${this.escapeHtml(tool.name)}</strong>
                    <small style="color: #999; margin-left: 5px;">(${tool.source || 'local'})</small>
                </label>
            </div>
        `).join('');
    },

    getTypeIcon(type) {
        const icons = { 'chat': '💬', 'coder': '💻', 'researcher': '📊', 'custom': '⚙️' };
        return icons[type] || '⚙️';
    },

    getTypeName(type) {
        const names = { 'chat': '聊天助手', 'coder': '代码助手', 'researcher': '研究助手', 'custom': '自定义' };
        return names[type] || '自定义';
    },

    getModeIcon(mode) {
        const icons = { 'plan': '📋', 'react': '🔄', 'direct': '⚡' };
        return icons[mode] || '📋';
    },

    getModeName(mode) {
        const names = { 'plan': 'Plan模式', 'react': 'ReAct模式', 'direct': 'Direct模式' };
        return names[mode] || 'Plan模式';
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
        return date.toLocaleDateString('zh-CN') + ' ' + date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    }
};
