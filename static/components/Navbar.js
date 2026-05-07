// Navigation Component (v2 - matches design system)
const Navigation = {
    container: null,

    render(container) {
        this.container = container;

        // Check if we're on a locked agent chat page
        const hash = window.location.hash || '';
        const isLockedChat = hash.includes('agent_id=');

        if (isLockedChat) {
            container.innerHTML = `
                <nav class="navbar">
                    <div class="navbar-brand">
                        <a href="/static/agent_manager.html" style="color: var(--text-primary); text-decoration: none; display: flex; align-items: center; gap: var(--space-2);">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
                            <h1>返回Agent管理</h1>
                        </a>
                    </div>
                </nav>
            `;
        } else {
            container.innerHTML = `
                <nav class="navbar">
                    <div class="navbar-brand">
                        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a4 4 0 0 1 4 4v2a4 4 0 0 1-8 0V6a4 4 0 0 1 4-4z"/><path d="M16 14h.01"/><path d="M8 14h.01"/><path d="M12 18v4"/><path d="M8 22h8"/><path d="M5 12a7 7 0 0 0 14 0"/></svg>
                        <h1>Quest3</h1>
                    </div>
                    <div class="navbar-nav">
                        <a href="/static/agent_manager.html" class="nav-btn">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                            聊天
                        </a>
                        <a href="/static/agent_manager.html" class="nav-btn">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="9" cy="16" r="1"/><circle cx="15" cy="16" r="1"/><path d="M12 2v4"/><path d="M8 6h8"/></svg>
                            Agent管理
                        </a>
                        <a href="/static/mcp_manager.html" class="nav-btn">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
                            MCP管理
                        </a>
                        <a href="/static/skill_manager.html" class="nav-btn">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
                            Skill管理
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
