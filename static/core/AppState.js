// AppState - Global State Management
const AppState = {
    _state: {
        currentModule: 'chat',
        currentSessionId: null,
        currentAgentId: null,
        agents: [],
        sessions: [],
        mcpServers: [],
        tools: []
    },
    _listeners: [],

    get(key) {
        return this._state[key];
    },

    set(key, value) {
        const oldValue = this._state[key];
        if (oldValue === value) return this;

        this._state[key] = value;
        this._listeners.forEach(cb => {
            try {
                cb(key, value, oldValue);
            } catch (e) {
                console.error('State listener error:', e);
            }
        });
        return this;
    },

    subscribe(callback) {
        this._listeners.push(callback);
        return () => {
            this._listeners = this._listeners.filter(cb => cb !== callback);
        };
    },

    getState() {
        return { ...this._state };
    }
};
