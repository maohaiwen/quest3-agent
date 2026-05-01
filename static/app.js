// App.js - Main Application Entry Point

// Expose Navigation globally for Router (must be before DOMContentLoaded)
window.Navigation = Navigation;

// Initialize application
document.addEventListener('DOMContentLoaded', () => {
    // Initialize Toast container
    Toast.init();

    // Initialize Navigation
    Navigation.render(document.getElementById('navbar'));

    // Initialize Router
    Router.init();

    // Register modules
    Router.register('chat', ChatModule);
    Router.register('agent', AgentModule);
    Router.register('mcp', MCPModule);

    // Set default hash if none
    if (!window.location.hash) {
        // Redirect to agent_manager if no hash and no agent_id param
        const params = new URLSearchParams(window.location.search);
        if (!params.get('agent_id')) {
            window.location.href = '/static/agent_manager.html';
            return;
        }
        Router.navigate('chat');
    }

    console.log('Quest3 Agent SPA initialized');
});
