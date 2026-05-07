// Quest3 Agent - Shared Navigation Component (v2 - Responsive)

const SharedNav = {
    _drawerOpen: false,

    render(container, options = {}) {
        const { active = '' } = options;
        const currentUser = typeof Auth !== 'undefined' ? Auth.getCurrentUser() : null;

        const items = [
            { id: 'agents', label: 'Agent管理', href: '/static/agent_manager.html', icon: 'svg-robot' },
            { id: 'mcp', label: 'MCP管理', href: '/static/mcp_manager.html', icon: 'svg-link' },
            { id: 'skills', label: '技能管理', href: '/static/skill_manager.html', icon: 'svg-tool' },
            { id: 'playground', label: '多智能体协作', href: '/static/collaboration_playground.html', icon: 'svg-flask' },
            { id: 'settings', label: '设置', href: '/static/settings.html', icon: 'svg-gear' },
        ];

        // Desktop nav items
        const navItemsHtml = items.map(item => `
            <a href="${item.href}"
               class="nav-btn ${item.id === active ? 'active' : ''}"
               ${item.id === active ? 'aria-current="page"' : ''}>
                ${this._getIcon(item.icon)}
                <span>${item.label}</span>
            </a>
        `).join('');

        // Mobile drawer items
        const drawerItemsHtml = items.map(item => `
            <a href="${item.href}"
               class="nav-mobile-item ${item.id === active ? 'active' : ''}"
               ${item.id === active ? 'aria-current="page"' : ''}>
                ${this._getIcon(item.icon)}
                <span>${item.label}</span>
            </a>
        `).join('');

        const logoutHtml = currentUser ? `
            <button class="nav-btn" onclick="Auth.logout()" aria-label="退出登录">
                ${this._getIcon('svg-logout')}
                <span class="hidden-mobile">退出</span>
            </button>
        ` : '';

        container.innerHTML = `
            <nav class="page-header" role="navigation">
                <a href="/static/agent_manager.html" class="page-header-brand">
                    ${this._getIcon('svg-logo')}
                    <span>Quest3</span>
                </a>

                <div class="page-header-nav">
                    ${navItemsHtml}
                </div>

                <div class="page-header-actions">
                    ${logoutHtml}
                    <button class="nav-hamburger" onclick="SharedNav.toggleDrawer()" aria-label="菜单" aria-expanded="false">
                        <svg viewBox="0 0 24 24"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
                    </button>
                </div>
            </nav>

            <!-- Mobile drawer overlay -->
            <div class="nav-mobile-overlay" onclick="SharedNav.closeDrawer()"></div>

            <!-- Mobile drawer -->
            <div class="nav-mobile-drawer" role="dialog" aria-label="导航菜单">
                <div class="nav-mobile-drawer-header">
                    <h2>Quest3 Agent</h2>
                    <button class="nav-mobile-drawer-close" onclick="SharedNav.closeDrawer()" aria-label="关闭菜单">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                    </button>
                </div>
                <div class="nav-mobile-drawer-items">
                    ${drawerItemsHtml}
                </div>
                ${currentUser ? `
                    <div class="nav-mobile-drawer-footer">
                        <button class="nav-mobile-item" onclick="Auth.logout()">
                            ${this._getIcon('svg-logout')}
                            <span>退出登录</span>
                        </button>
                    </div>
                ` : ''}
            </div>
        `;
    },

    toggleDrawer() {
        this._drawerOpen ? this.closeDrawer() : this.openDrawer();
    },

    openDrawer() {
        this._drawerOpen = true;
        const overlay = document.querySelector('.nav-mobile-overlay');
        const drawer = document.querySelector('.nav-mobile-drawer');
        const btn = document.querySelector('.nav-hamburger');
        if (overlay) overlay.classList.add('open');
        if (drawer) drawer.classList.add('open');
        if (btn) btn.setAttribute('aria-expanded', 'true');
        document.body.style.overflow = 'hidden';
    },

    closeDrawer() {
        this._drawerOpen = false;
        const overlay = document.querySelector('.nav-mobile-overlay');
        const drawer = document.querySelector('.nav-mobile-drawer');
        const btn = document.querySelector('.nav-hamburger');
        if (overlay) overlay.classList.remove('open');
        if (drawer) drawer.classList.remove('open');
        if (btn) btn.setAttribute('aria-expanded', 'false');
        document.body.style.overflow = '';
    },

    _getIcon(name) {
        const icons = {
            'svg-logo': '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a4 4 0 0 1 4 4v2a4 4 0 0 1-8 0V6a4 4 0 0 1 4-4z"/><path d="M16 14h.01"/><path d="M8 14h.01"/><path d="M12 18v4"/><path d="M8 22h8"/><path d="M5 12a7 7 0 0 0 14 0"/></svg>',
            'svg-robot': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="9" cy="16" r="1"/><circle cx="15" cy="16" r="1"/><path d="M12 2v4"/><path d="M8 6h8"/></svg>',
            'svg-link': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
            'svg-tool': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
            'svg-flask': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6"/><path d="M10 9V3"/><path d="M14 9V3"/><path d="M8.5 14h7"/><path d="M7 22h10a2 2 0 0 0 1.83-2.73L14.35 10H9.65L5.17 19.27A2 2 0 0 0 7 22z"/></svg>',
            'svg-gear': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
            'svg-logout': '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>'
        };
        return icons[name] || '';
    }
};
