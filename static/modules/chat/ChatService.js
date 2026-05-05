// Chat Service - WebSocket Management
const ChatService = {
    ws: null,
    sessionId: null,
    agentId: null,
    reconnectAttempts: 0,
    maxReconnectAttempts: 3,
    messageHandlers: {},
    isConnected: false,
    _reconnectTimer: null,
    _intentionalClose: false,

    connect(sessionId, agentId) {
        // Cancel any pending reconnection timer
        if (this._reconnectTimer) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }

        this.sessionId = sessionId;
        this.agentId = agentId;
        this._intentionalClose = false;

        if (this.ws) {
            // Mark as intentional close to prevent onclose from reconnecting
            this._intentionalClose = true;
            // Remove event handlers before closing to prevent onclose
            // from triggering reconnection
            this.ws.onopen = null;
            this.ws.onmessage = null;
            this.ws.onclose = null;
            this.ws.onerror = null;
            this.ws.close();
        }

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/api/chat/stream`;

        try {
            this.ws = new WebSocket(wsUrl);
            this._bindEvents();
        } catch (error) {
            console.error('WebSocket connection error:', error);
            this._triggerHandler('error', { error: error.message });
        }
    },

    _bindEvents() {
        this.ws.onopen = () => {
            this.reconnectAttempts = 0;
            this._intentionalClose = false;
            this.isConnected = true;
            this._triggerHandler('connected', {
                sessionId: this.sessionId,
                agentId: this.agentId
            });

            // Send initial message
            const message = { session_id: this.sessionId };
            if (this.agentId) {
                message.agent_id = this.agentId;
            }
            this.ws.send(JSON.stringify(message));
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this._triggerHandler(data.type, data);
            } catch (error) {
                console.error('Message parse error:', error);
            }
        };

        this.ws.onclose = () => {
            this.isConnected = false;
            this._triggerHandler('disconnected', {});

            // Don't reconnect if we intentionally closed the connection
            if (this._intentionalClose) {
                this._intentionalClose = false;
                return;
            }

            // Cancel any existing reconnect timer before scheduling a new one
            if (this._reconnectTimer) {
                clearTimeout(this._reconnectTimer);
                this._reconnectTimer = null;
            }

            if (this.reconnectAttempts < this.maxReconnectAttempts) {
                this.reconnectAttempts++;
                this._reconnectTimer = setTimeout(() => {
                    this._reconnectTimer = null;
                    this.connect(this.sessionId, this.agentId);
                }, 3000);
            }
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this._triggerHandler('error', { error: error.message || 'WebSocket error' });
        };
    },

    send(message, deepThinking = false) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                message,
                deep_thinking: deepThinking
            }));
            return true;
        }
        return false;
    },

    loadMoreHistory(count = 40) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                action: "load_more_history",
                before: count
            }));
            return true;
        }
        return false;
    },

    on(event, handler) {
        if (!this.messageHandlers[event]) {
            this.messageHandlers[event] = [];
        }
        this.messageHandlers[event].push(handler);
    },

    off(event, handler) {
        if (!this.messageHandlers[event]) return;
        this.messageHandlers[event] = this.messageHandlers[event].filter(h => h !== handler);
    },

    _triggerHandler(event, data) {
        const handlers = this.messageHandlers[event] || [];
        handlers.forEach(handler => {
            try {
                handler(data);
            } catch (error) {
                console.error(`Handler error for event ${event}:`, error);
            }
        });
    },

    disconnect() {
        // Cancel any pending reconnection timer
        if (this._reconnectTimer) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }

        this._intentionalClose = true;

        if (this.ws) {
            // Remove event handlers before closing to prevent reconnection
            this.ws.onopen = null;
            this.ws.onmessage = null;
            this.ws.onclose = null;
            this.ws.onerror = null;
            this.ws.close();
            this.ws = null;
        }
        this.isConnected = false;
    },

    setAgent(agentId) {
        this.agentId = agentId;
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ agent_id: agentId }));
        }
    }
};
