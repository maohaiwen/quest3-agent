// Quest3 Agent - Shared Tab Switching

// Usage: add data-tab="tabName" to tab buttons and data-tab-panel="tabName" to tab panels
// Call Tabs.init() after DOM is ready, or use data-tabs="groupName" for multiple tab groups

const Tabs = {
    init(container = document) {
        container.querySelectorAll('[data-tab]').forEach(btn => {
            btn.addEventListener('click', () => {
                const tabGroup = btn.closest('[data-tabs]') || container;
                const tabName = btn.dataset.tab;

                // Use parent scope for panels if they're not inside the tab group
                const panelScope = tabGroup.querySelector('[data-tab-panel]')
                    ? tabGroup
                    : tabGroup.parentElement || container;

                // Deactivate all tabs in group
                tabGroup.querySelectorAll('[data-tab]').forEach(t => t.classList.remove('active'));
                panelScope.querySelectorAll('[data-tab-panel]').forEach(p => {
                    p.classList.remove('active');
                    p.style.display = 'none';
                });

                // Activate clicked tab and panel
                btn.classList.add('active');
                const panel = panelScope.querySelector(`[data-tab-panel="${tabName}"]`);
                if (panel) {
                    panel.classList.add('active');
                    panel.style.display = '';
                }

                // Fire custom event
                tabGroup.dispatchEvent(new CustomEvent('tab-change', {
                    detail: { tab: tabName },
                    bubbles: true
                }));
            });
        });
    }
};

document.addEventListener('DOMContentLoaded', () => Tabs.init());
