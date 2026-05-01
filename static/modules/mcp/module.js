// MCP Module
const MCPModule = {
    name: 'mcp',
    servers: [],
    allTools: [],
    currentTestTool: null,

    init() {
        this.loadServers();
        this.loadTools();
    },

    render(container) {
        MCPView.render(container);
    },

    destroy() {
        this.currentTestTool = null;
    },

    async loadServers() {
        try {
            const data = await API.get('/api/mcp/servers');
            this.servers = data.servers || [];
            MCPView.renderServers(this.servers);
        } catch (error) {
            console.error('Failed to load servers:', error);
            Toast.error('加载服务器列表失败');
        }
    },

    async loadTools() {
        try {
            // Load MCP tools from servers
            const serverTools = [];
            for (const server of this.servers) {
                if (server.status === 'connected') {
                    try {
                        const data = await MCPService.getTools(server.id);
                        if (data.tools) {
                            data.tools.forEach(tool => {
                                serverTools.push({
                                    ...tool,
                                    source: 'mcp',
                                    server_name: server.name,
                                    server_id: server.id
                                });
                            });
                        }
                    } catch (e) {
                        console.error(`Failed to load tools from server ${server.id}:`, e);
                    }
                }
            }

            // Load local tools
            const localData = await API.get('/tools');
            const localTools = (localData.tools || []).map(tool => ({
                ...tool,
                source: 'local'
            }));

            this.allTools = [...serverTools, ...localTools];
            MCPView.renderTools(this.allTools);
        } catch (error) {
            console.error('Failed to load tools:', error);
        }
    },

    switchTab(tab) {
        MCPView.switchTab(tab);
        if (tab === 'tools') {
            this.loadTools();
        }
    },

    filterTools() {
        const search = document.getElementById('toolSearch')?.value?.toLowerCase() || '';
        const filter = document.getElementById('toolFilter')?.value || 'all';

        let filteredTools = this.allTools;

        if (search) {
            filteredTools = filteredTools.filter(tool =>
                tool.name.toLowerCase().includes(search) ||
                (tool.description && tool.description.toLowerCase().includes(search))
            );
        }

        if (filter !== 'all') {
            filteredTools = filteredTools.filter(tool => tool.source === filter);
        }

        MCPView.renderTools(filteredTools);
    },

    openAddModal() {
        Modal.show({
            title: '添加 MCP 服务器',
            content: `
                <div class="form-group">
                    <label>服务器名称 *</label>
                    <input type="text" class="form-control" id="serverName" placeholder="例如：阿里云 Code Interpreter">
                </div>
                <div class="form-group">
                    <label>服务器 URL *</label>
                    <input type="url" class="form-control" id="serverUrl" placeholder="https://dashscope.aliyuncs.com/api/v1/mcps/code_interpreter_mcp/mcp">
                </div>
                <div class="form-group">
                    <label>服务器类型</label>
                    <select class="form-control" id="serverType">
                        <option value="standard">标准 MCP 服务器</option>
                        <option value="streamable">流式 HTTP 端点 (如阿里云)</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>描述</label>
                    <textarea class="form-control" id="serverDescription" placeholder="描述此服务器提供的工具..."></textarea>
                </div>
                <div class="form-group">
                    <label>鉴权头 (可选)</label>
                    <input type="text" class="form-control" id="authHeader" placeholder="Authorization: Bearer YOUR_API_KEY">
                </div>
                <div class="form-group">
                    <label>自定义 Headers (可选，每行一个，格式: key:value)</label>
                    <textarea class="form-control" id="customHeaders" placeholder="Content-Type: application/json"></textarea>
                </div>
            `,
            footer: `
                <button class="btn btn-secondary" onclick="Modal.close()">取消</button>
                <button class="btn btn-primary" onclick="MCPModule.addServer()">添加</button>
            `,
            width: '600px'
        });
    },

    async addServer() {
        const name = document.getElementById('serverName')?.value?.trim();
        const url = document.getElementById('serverUrl')?.value?.trim();
        const description = document.getElementById('serverDescription')?.value?.trim();
        const serverType = document.getElementById('serverType')?.value;
        const authHeader = document.getElementById('authHeader')?.value?.trim();
        const headers = document.getElementById('customHeaders')?.value?.trim();

        if (!name || !url) {
            Toast.error('请填写服务器名称和 URL');
            return;
        }

        try {
            await API.post('/api/mcp/servers', {
                name,
                url,
                description,
                server_type: serverType,
                auth_header: authHeader,
                headers
            });

            Toast.success('服务器添加成功！');
            Modal.close();
            await this.loadServers();
        } catch (error) {
            console.error('Failed to add server:', error);
            Toast.error(error.message || '添加失败');
        }
    },

    async connectServer(serverId) {
        try {
            Toast.show('正在连接...', 'warning', 10000);
            const data = await MCPService.connectServer(serverId);
            if (data.success) {
                Toast.success('连接成功！');
            } else {
                Toast.error(data.message || '连接失败');
            }
            await this.loadServers();
            await this.loadTools();
        } catch (error) {
            console.error('Failed to connect server:', error);
            Toast.error(error.message || '连接失败');
        }
    },

    async disconnectServer(serverId) {
        if (!confirm('确定要断开此服务器的连接吗？')) {
            return;
        }

        try {
            await MCPService.disconnectServer(serverId);
            Toast.success('已断开连接');
            await this.loadServers();
            await this.loadTools();
        } catch (error) {
            console.error('Failed to disconnect server:', error);
            Toast.error('操作失败');
        }
    },

    async testServer(serverId) {
        try {
            const data = await MCPService.testServer(serverId);
            if (data.connected) {
                Toast.success(`连接成功！延迟: ${data.latency_ms}ms, 工具数: ${data.tool_count}`);
            } else {
                Toast.error(data.error || '连接失败');
            }
        } catch (error) {
            console.error('Failed to test server:', error);
            Toast.error(error.message || '测试失败');
        }
    },

    async deleteServer(serverId) {
        const server = this.servers.find(s => s.id === serverId);
        if (!server) return;

        if (!confirm(`确定要删除服务器 "${server.name}" 吗？此操作不可恢复。`)) {
            return;
        }

        try {
            await MCPService.deleteServer(serverId);
            Toast.success('服务器已删除');
            await this.loadServers();
            await this.loadTools();
        } catch (error) {
            console.error('Failed to delete server:', error);
            Toast.error('删除失败');
        }
    },

    openTestModal(toolName, source, serverId) {
        this.currentTestTool = { name: toolName, source, serverId };

        Modal.show({
            title: `测试工具: ${toolName}`,
            content: `
                <div class="form-group">
                    <label>参数 (JSON格式)</label>
                    <textarea class="form-control" id="testArguments" placeholder='{"param1": "value1"}'></textarea>
                </div>
                <div id="testResult" style="display: none; margin-top: 16px;"></div>
            `,
            footer: `
                <button class="btn btn-secondary" onclick="Modal.close()">关闭</button>
                <button class="btn btn-primary" onclick="MCPModule.testTool()">测试</button>
            `,
            width: '600px'
        });
    },

    async testTool() {
        if (!this.currentTestTool) return;

        const argsText = document.getElementById('testArguments')?.value?.trim() || '{}';
        const resultDiv = document.getElementById('testResult');

        let args = {};
        try {
            args = JSON.parse(argsText);
        } catch (e) {
            Toast.error('参数 JSON 格式错误');
            return;
        }

        try {
            let data;
            if (this.currentTestTool.source === 'local') {
                data = await MCPService.callLocalTool(this.currentTestTool.name, args);
            } else {
                data = await MCPService.callTool(this.currentTestTool.serverId, this.currentTestTool.name, args);
            }

            if (resultDiv) {
                resultDiv.style.display = 'block';
                resultDiv.style.background = '#e8f5e9';
                resultDiv.style.border = '1px solid #4caf50';
                resultDiv.style.borderRadius = '8px';
                resultDiv.style.padding = '16px';
                resultDiv.innerHTML = `
                    <div style="font-weight: 600; margin-bottom: 8px; color: #333;">测试成功!</div>
                    <pre style="white-space: pre-wrap; font-size: 13px;">${JSON.stringify(data.result || data, null, 2)}</pre>
                `;
            }
        } catch (error) {
            console.error('Tool test failed:', error);
            if (resultDiv) {
                resultDiv.style.display = 'block';
                resultDiv.style.background = '#ffebee';
                resultDiv.style.border = '1px solid #f44336';
                resultDiv.style.borderRadius = '8px';
                resultDiv.style.padding = '16px';
                resultDiv.innerHTML = `
                    <div style="font-weight: 600; margin-bottom: 8px; color: #d32f2f;">测试失败</div>
                    <pre style="white-space: pre-wrap; font-size: 13px; color: #d32f2f;">${error.message}</pre>
                `;
            }
        }
    }
};
