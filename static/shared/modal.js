// Quest3 Agent - Shared Modal Helpers

const SharedModal = {
    open(modalId) {
        const el = document.getElementById(modalId);
        if (el) el.classList.add('active');
    },

    close(modalId) {
        const el = document.getElementById(modalId);
        if (el) el.classList.remove('active');
    },

    toggle(modalId) {
        const el = document.getElementById(modalId);
        if (el) el.classList.toggle('active');
    },

    // Auto-init: close on overlay click and Escape key
    init() {
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('modal') && e.target.classList.contains('active')) {
                e.target.classList.remove('active');
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                document.querySelectorAll('.modal.active').forEach(m => m.classList.remove('active'));
            }
        });
    }
};

// Auto-initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => SharedModal.init());
