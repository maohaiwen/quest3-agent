// Quest3 Agent - Shared Utilities

const Utils = {
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    formatDate(dateString) {
        if (!dateString) return '';
        const date = new Date(dateString);
        const tz = { timeZone: 'Asia/Shanghai' };
        return date.toLocaleDateString('zh-CN', tz) + ' ' +
            date.toLocaleTimeString('zh-CN', { ...tz, hour: '2-digit', minute: '2-digit' });
    },

    formatRelativeTime(dateString) {
        if (!dateString) return '';
        const date = new Date(dateString);
        const now = new Date();
        const diff = now - date;

        if (diff < 60000) return '刚刚';
        if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`;
        if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`;
        return date.toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai' });
    }
};
