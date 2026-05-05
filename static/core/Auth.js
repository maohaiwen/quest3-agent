// Auth - Simple authentication module based on localStorage
const Auth = {
    STORAGE_KEY: 'quest3_user',

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
            localStorage.setItem(this.STORAGE_KEY, JSON.stringify(data.user));
            return data.user;
        } catch (e) {
            throw e;
        }
    },

    logout() {
        localStorage.removeItem(this.STORAGE_KEY);
        window.location.href = '/static/login.html';
    },

    getCurrentUser() {
        try {
            const stored = localStorage.getItem(this.STORAGE_KEY);
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
        return !!this.getCurrentUser();
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
        localStorage.setItem(this.STORAGE_KEY, JSON.stringify(user));
    }
};
