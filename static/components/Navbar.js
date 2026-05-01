// Navigation Component
const Navigation = {
    container: null,

    render(container) {
        this.container = container;

        // Check if we're on a locked agent chat page
        const hash = window.location.hash || '';
        const isLockedChat = hash.includes('agent_id=');

        if (isLockedChat) {
            // Show minimal navbar with only back button
            container.innerHTML = `
                <nav class="navbar">
                    <div class="navbar-brand">
                        <a href="/static/agent_manager.html" style="color: white; text-decoration: none; display: flex; align-items: center; gap: 8px;">
                            <span>←</span>
                            <h1>🤖 返回Agent管理</h1>
                        </a>
                    </div>
                </nav>
            `;
        } else {
            // Show full navbar
            container.innerHTML = `
                <nav class="navbar">
                    <div class="navbar-brand">
                        <h1>🤖 Quest3 Agent</h1>
                    </div>
                    <div class="navbar-nav">
                        <a href="/static/agent_manager.html" class="nav-btn">
                            💬 聊天
                        </a>
                        <a href="/static/agent_manager.html" class="nav-btn">
                            🤖 Agent管理
                        </a>
                        <a href="/static/mcp_manager.html" class="nav-btn">
                            🔗 MCP管理
                        </a>
                        <a href="/static/skill_manager.html" class="nav-btn">
                            🛠️ Skill管理
                        </a>
                    </div>
                </nav>
            `;
        }
    },

    setActive(route) {
        // No-op since we use direct links now
    }
};
