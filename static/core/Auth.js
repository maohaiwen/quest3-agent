// Auth - JWT-based authentication module
const Auth = {
    USER_KEY: 'quest3_user',
    TOKEN_KEY: 'quest3_access_token',
    REFRESH_KEY: 'quest3_refresh_token',

    async login(username, password) {
        try {
            const res = await fetch('/api/users/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: res.statusText }));
                throw new Error(err.detail || 'Login failed');
            }
            const data = await res.json();
            // Store JWT tokens
            localStorage.setItem(this.TOKEN_KEY, data.access_token);
            localStorage.setItem(this.REFRESH_KEY, data.refresh_token);
            localStorage.setItem(this.USER_KEY, JSON.stringify(data.user));
            return data.user;
        } catch (e) {
            throw e;
        }
    },

    logout() {
        localStorage.removeItem(this.TOKEN_KEY);
        localStorage.removeItem(this.REFRESH_KEY);
        localStorage.removeItem(this.USER_KEY);
        window.location.href = '/static/login.html';
    },

    getAccessToken() {
        return localStorage.getItem(this.TOKEN_KEY);
    },

    getRefreshToken() {
        return localStorage.getItem(this.REFRESH_KEY);
    },

    getCurrentUser() {
        try {
            const stored = localStorage.getItem(this.USER_KEY);
            return stored ? JSON.parse(stored) : null;
        } catch {
            return null;
        }
    },

    isAdmin() {
        const user = this.getCurrentUser();
        return user && user.role === 'admin';
    },

    isLoggedIn() {
        return !!this.getAccessToken();
    },

    // Check auth on page load; redirect to login if not logged in
    requireAuth() {
        if (!this.isLoggedIn()) {
            window.location.href = '/static/login.html';
            return false;
        }
        return true;
    },

    // Update stored user info
    updateUser(user) {
        localStorage.setItem(this.USER_KEY, JSON.stringify(user));
    },

    // Refresh the access token using the refresh token
    async refreshAccessToken() {
        const refreshToken = this.getRefreshToken();
        if (!refreshToken) return false;

        try {
            const res = await fetch('/api/users/refresh', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: refreshToken })
            });
            if (!res.ok) return false;

            const data = await res.json();
            localStorage.setItem(this.TOKEN_KEY, data.access_token);
            return true;
        } catch {
            return false;
        }
    }
};
