// MCP Service
const MCPService = {
    async listServers() {
        return API.get('/api/mcp/servers');
    },

    async addServer(data) {
        return API.post('/api/mcp/servers', data);
    },

    async deleteServer(id) {
        return API.delete(`/api/mcp/servers/${id}`);
    },

    async connectServer(id) {
        return API.post(`/api/mcp/servers/${id}/connect`);
    },

    async disconnectServer(id) {
        return API.post(`/api/mcp/servers/${id}/disconnect`);
    },

    async testServer(id) {
        return API.get(`/api/mcp/servers/${id}/test`);
    },

    async getTools(serverId) {
        return API.get(`/api/mcp/servers/${serverId}/tools`);
    },

    async callTool(serverId, toolName, args) {
        return API.post(`/api/mcp/servers/${serverId}/tools/call`, {
            tool_name: toolName,
            arguments: args
        });
    },

    async callLocalTool(toolName, args) {
        return API.post('/api/mcp/call', {
            tool_name: toolName,
            arguments: args
        });
    }
};
