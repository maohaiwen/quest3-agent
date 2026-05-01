// Router - Hash-based Routing
const Router = {
    _routes: {},
    _currentRoute: null,
    _lastHash: null,

    init() {
        window.addEventListener('hashchange', () => this._handleRoute());
        window.addEventListener('load', () => this._handleRoute());
    },

    register(moduleName, module) {
        this._routes[moduleName] = module;
    },

    navigate(hash) {
        if (!hash) hash = 'chat';
        if (!hash.startsWith('#')) hash = '#' + hash;
        window.location.hash = hash;
    },

    getCurrentRoute() {
        return this._currentRoute;
    },

    _handleRoute() {
        const hashWithParams = window.location.hash.slice(1) || 'chat';
        // Split hash from query params (e.g., "chat?agent_id=xxx" -> "chat")
        const [hash] = hashWithParams.split('?');

        // Prevent double rendering on initial load
        if (hash === this._lastHash) {
            return;
        }
        this._lastHash = hash;

        const route = this._routes[hash];

        // Destroy previous route
        if (this._currentRoute && this._currentRoute.destroy) {
            try {
                this._currentRoute.destroy();
            } catch (e) {
                console.error('Route destroy error:', e);
            }
        }

        if (!route) {
            console.warn(`Route not found: ${hash}, redirecting to chat`);
            this.navigate('chat');
            return;
        }

        this._currentRoute = route;
        AppState.set('currentModule', hash);

        // Render in main content area
        const container = document.getElementById('main-content');
        if (container) {
            container.innerHTML = '';
            if (route.init) route.init();
            if (route.render) route.render(container);
        }

        // Update navigation
        if (window.Navigation) {
            window.Navigation.setActive(hash);
        }
    }
};
