// Chat Service - WebSocket Management
const ChatService = {
    ws: null,
    sessionId: null,
    agentId: null,
    reconnectAttempts: 0,
    maxReconnectAttempts: 3,
    messageHandlers: {},
    isConnected: false,

    connect(sessionId, agentId) {
        this.sessionId = sessionId;
        this.agentId = agentId;

        if (this.ws) {
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

            if (this.reconnectAttempts < this.maxReconnectAttempts) {
                this.reconnectAttempts++;
                setTimeout(() => this.connect(this.sessionId, this.agentId), 3000);
            }
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this._triggerHandler('error', { error: error.message });
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
        if (this.ws) {
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
