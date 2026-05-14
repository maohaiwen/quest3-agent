// API Base Module — with JWT auth headers
const API = {
    baseUrl: '',

    _getHeaders() {
        const headers = { 'Content-Type': 'application/json' };
        const token = localStorage.getItem('quest3_access_token');
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        return headers;
    },

    async _handleAuthError(res) {
        // If 401, try refreshing the token once
        if (res.status === 401) {
            const refreshed = await Auth.refreshAccessToken();
            if (refreshed) {
                return true; // Caller should retry
            }
            // Refresh failed — force re-login
            Auth.logout();
        }
        return false;
    },

    async get(url) {
        let res = await fetch(this.baseUrl + url, { headers: this._getHeaders() });
        if (res.status === 401) {
            const retry = await this._handleAuthError(res);
            if (retry) res = await fetch(this.baseUrl + url, { headers: this._getHeaders() });
        }
        if (!res.ok) {
            const error = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(error.detail || res.statusText);
        }
        return res.json();
    },

    async post(url, data = {}) {
        let res = await fetch(this.baseUrl + url, {
            method: 'POST',
            headers: this._getHeaders(),
            body: JSON.stringify(data)
        });
        if (res.status === 401) {
            const retry = await this._handleAuthError(res);
            if (retry) {
                res = await fetch(this.baseUrl + url, {
                    method: 'POST',
                    headers: this._getHeaders(),
                    body: JSON.stringify(data)
                });
            }
        }
        if (!res.ok) {
            const error = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(error.detail || res.statusText);
        }
        return res.json();
    },

    async put(url, data = {}) {
        let res = await fetch(this.baseUrl + url, {
            method: 'PUT',
            headers: this._getHeaders(),
            body: JSON.stringify(data)
        });
        if (res.status === 401) {
            const retry = await this._handleAuthError(res);
            if (retry) {
                res = await fetch(this.baseUrl + url, {
                    method: 'PUT',
                    headers: this._getHeaders(),
                    body: JSON.stringify(data)
                });
            }
        }
        if (!res.ok) {
            const error = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(error.detail || res.statusText);
        }
        return res.json();
    },

    async delete(url) {
        let res = await fetch(this.baseUrl + url, {
            method: 'DELETE',
            headers: this._getHeaders()
        });
        if (res.status === 401) {
            const retry = await this._handleAuthError(res);
            if (retry) {
                res = await fetch(this.baseUrl + url, {
                    method: 'DELETE',
                    headers: this._getHeaders()
                });
            }
        }
        if (!res.ok) {
            const error = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(error.detail || res.statusText);
        }
        return res.json();
    }
};
