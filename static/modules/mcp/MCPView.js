// MCP View
const MCPView = {
    container: null,
    currentTab: 'servers',

    render(container) {
        this.container = container;
        container.innerHTML = `
            <div style="padding: 24px;">
                <h2 style="font-size: 20px; font-weight: 600; margin-bottom: 20px;">🔗 MCP管理</h2>

                <div class="tabs">
                    <button class="tab active" onclick="MCPModule.switchTab('servers')">服务器</button>
                    <button class="tab" onclick="MCPModule.switchTab('tools')">工具</button>
                </div>

                <!-- Servers Tab -->
                <div id="serversTab">
                    <div class="card" onclick="MCPModule.openAddModal()" style="cursor: pointer; text-align: center; border: 2px dashed var(--border-color); background: var(--sidebar-bg);">
                        <div style="font-size: 48px; margin-bottom: 12px;">➕</div>
                        <h3 style="color: #333; margin-bottom: 8px;">添加 MCP 服务器</h3>
                        <p style="color: #666; font-size: 14px;">连接到新的 MCP 工具服务器</p>
                    </div>

                    <h3 style="margin: 24px 0 16px; font-size: 16px; font-weight: 600;">MCP 服务器列表</h3>
                    <div id="serversList" class="servers-list" style="display: flex; flex-direction: column; gap: 16px;"></div>
                </div>

                <!-- Tools Tab -->
                <div id="toolsTab" style="display: none;">
                    <div class="filter-controls" style="display: flex; gap: 12px; margin-bottom: 16px;">
                        <input type="text" class="form-control" id="toolSearch" placeholder="搜索工具..." oninput="MCPModule.filterTools()">
                        <select class="form-control" id="toolFilter" onchange="MCPModule.filterTools()" style="width: 150px;">
                            <option value="all">全部</option>
                            <option value="mcp">MCP 服务器</option>
                            <option value="local">本地工具</option>
                        </select>
                    </div>
                    <div id="toolsList" class="tools-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px;"></div>
                </div>
            </div>
        `;

        MCPModule.loadServers();
        MCPModule.loadTools();
    },

    switchTab(tab) {
        this.currentTab = tab;

        document.querySelectorAll('.tab').forEach((t, i) => {
            t.classList.toggle('active', (tab === 'servers' && i === 0) || (tab === 'tools' && i === 1));
        });

        document.getElementById('serversTab').style.display = tab === 'servers' ? 'block' : 'none';
        document.getElementById('toolsTab').style.display = tab === 'tools' ? 'block' : 'none';
    },

    renderServers(servers) {
        const list = document.getElementById('serversList');
        if (!list) return;

        if (!servers || servers.length === 0) {
            list.innerHTML = `
                <div class="empty-state">
                    <div class="icon">📡</div>
                    <h3>暂无 MCP 服务器</h3>
                    <p>点击上方卡片添加服务器</p>
                </div>
            `;
            return;
        }

        list.innerHTML = servers.map(server => `
            <div class="card" style="display: flex; gap: 16px; align-items: center;">
                <div class="server-status ${server.status || 'disconnected'}" style="
                    width: 48px;
                    height: 48px;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 24px;
                    background: ${server.status === 'connected' ? '#e8f5e9' : server.status === 'connecting' ? '#fff3cd' : '#f5f5f5'};
                    color: ${server.status === 'connected' ? '#4caf50' : server.status === 'connecting' ? '#ff9800' : '#999'};
                ">
                    ${server.status === 'connected' ? '✓' : server.status === 'connecting' ? '⟳' : '✗'}
                </div>
                <div style="flex: 1;">
                    <h3 style="color: #333; margin-bottom: 4px;">${this.escapeHtml(server.name)}</h3>
                    <div style="color: #666; font-size: 13px; margin-bottom: 8px;">${this.escapeHtml(server.url)}</div>
                    <div style="display: flex; gap: 16px; font-size: 13px; color: #666;">
                        <span>工具数: ${server.tool_count || 0}</span>
                        ${server.last_connected ? `<span>最后连接: ${this.formatDate(server.last_connected)}</span>` : ''}
                    </div>
                </div>
                <div style="display: flex; gap: 8px;">
                    ${server.status !== 'connected' ?
                        `<button class="btn btn-primary" onclick="MCPModule.connectServer('${server.id}')">连接</button>` :
                        `<button class="btn btn-secondary" onclick="MCPModule.disconnectServer('${server.id}')">断开</button>`
                    }
                    <button class="btn btn-secondary" onclick="MCPModule.testServer('${server.id}')">测试</button>
                    <button class="btn btn-danger" onclick="MCPModule.deleteServer('${server.id}')">删除</button>
                </div>
            </div>
        `).join('');
    },

    renderTools(tools) {
        const list = document.getElementById('toolsList');
        if (!list) return;

        if (!tools || tools.length === 0) {
            list.innerHTML = `
                <div class="empty-state" style="grid-column: 1 / -1;">
                    <div class="icon">🔧</div>
                    <h3>暂无可用工具</h3>
                    <p>添加并连接 MCP 服务器后可查看工具</p>
                </div>
            `;
            return;
        }

        list.innerHTML = tools.map(tool => {
            let paramsHtml = '<div style="font-size: 12px; color: #666;">无参数</div>';
            if (tool.input_schema && tool.input_schema.properties) {
                const params = Object.keys(tool.input_schema.properties);
                paramsHtml = `<div style="font-size: 12px; color: #666;">参数: ${params.join(', ')}</div>`;
            }

            return `
                <div class="card">
                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 12px;">
                        <div>
                            <div style="font-weight: 600; color: #333; font-size: 15px;">${this.escapeHtml(tool.name)}</div>
                            <span class="badge ${tool.source === 'mcp' ? '' : 'badge-success'}" style="
                                margin-top: 4px;
                                font-size: 11px;
                                padding: 2px 8px;
                                border-radius: 10px;
                                font-weight: 500;
                                background: ${tool.source === 'mcp' ? '#e3f2fd' : '#e8f5e9'};
                                color: ${tool.source === 'mcp' ? '#1976d2' : '#4caf50'};
                            ">
                                ${tool.source === 'mcp' ? 'MCP' : '本地'}
                                ${tool.source === 'mcp' && tool.server_name ? `(${this.escapeHtml(tool.server_name)})` : ''}
                            </span>
                        </div>
                    </div>
                    <p style="color: #666; font-size: 13px; margin-bottom: 12px; line-height: 1.4;">
                        ${this.escapeHtml(tool.description || '暂无描述')}
                    </p>
                    ${paramsHtml}
                    <div style="margin-top: 12px;">
                        <button class="btn btn-primary" onclick="MCPModule.openTestModal('${tool.name}', '${tool.source}', '${tool.server_id || ''}')">
                            测试
                        </button>
                    </div>
                </div>
            `;
        }).join('');
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
        return date.toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai' });
    }
};
