// Modal Component
const Modal = {
    overlay: null,

    show(options) {
        const { title, content, footer, onClose, width = '700px' } = options;

        this.overlay = document.createElement('div');
        this.overlay.className = 'modal-overlay active';
        this.overlay.id = 'modal-overlay';

        this.overlay.innerHTML = `
            <div class="modal" style="max-width: ${width};">
                <div class="modal-header">
                    <h2>${title}</h2>
                    <button class="modal-close" onclick="Modal.close()">&times;</button>
                </div>
                <div class="modal-body">${content}</div>
                ${footer ? `<div class="modal-footer">${footer}</div>` : ''}
            </div>
        `;

        this.overlay.addEventListener('click', (e) => {
            if (e.target === this.overlay) {
                this.close();
            }
        });

        document.body.appendChild(this.overlay);

        if (onClose) {
            this._onClose = onClose;
        }

        return this;
    },

    close() {
        if (this.overlay) {
            this.overlay.remove();
            this.overlay = null;
        }
        if (this._onClose) {
            this._onClose();
            this._onClose = null;
        }
    },

    setLoading(loading) {
        const footer = this.overlay?.querySelector('.modal-footer');
        if (!footer) return;
        const buttons = footer.querySelectorAll('button');
        buttons.forEach(btn => {
            btn.disabled = loading;
        });
    },

    showForm(formOptions) {
        const { title, fields, onSubmit, onCancel, submitText = '保存', width } = formOptions;

        const fieldsHtml = fields.map(field => {
            if (field.type === 'checkbox') {
                return `
                    <div class="form-group checkbox-group">
                        <input type="checkbox" id="${field.id}" ${field.checked ? 'checked' : ''}>
                        <label for="${field.id}">${field.label}</label>
                    </div>
                `;
            }
            if (field.type === 'select') {
                const optionsHtml = field.options.map(opt =>
                    `<option value="${opt.value}" ${opt.selected ? 'selected' : ''}>${opt.label}</option>`
                ).join('');
                return `
                    <div class="form-group">
                        <label for="${field.id}">${field.label}</label>
                        <select class="form-control" id="${field.id}">
                            ${optionsHtml}
                        </select>
                    </div>
                `;
            }
            if (field.type === 'textarea') {
                return `
                    <div class="form-group">
                        <label for="${field.id}">${field.label}</label>
                        <textarea class="form-control" id="${field.id}"
                            placeholder="${field.placeholder || ''}">${field.value || ''}</textarea>
                    </div>
                `;
            }
            return `
                <div class="form-group">
                    <label for="${field.id}">${field.label}</label>
                    <input type="${field.type || 'text'}" class="form-control"
                        id="${field.id}" placeholder="${field.placeholder || ''}"
                        value="${field.value || ''}" ${field.required ? 'required' : ''}>
                </div>
            `;
        }).join('');

        const footerHtml = `
            <button class="btn btn-secondary" onclick="Modal.close()">取消</button>
            <button class="btn btn-primary" id="modal-submit">${submitText}</button>
        `;

        this.show({
            title,
            content: `<div id="modal-form-container">${fieldsHtml}</div>`,
            footer: footerHtml,
            width: width
        });

        // Bind submit
        setTimeout(() => {
            const submitBtn = document.getElementById('modal-submit');
            if (submitBtn) {
                submitBtn.addEventListener('click', () => {
                    const formData = {};
                    fields.forEach(field => {
                        const el = document.getElementById(field.id);
                        if (!el) return;
                        if (field.type === 'checkbox') {
                            formData[field.id] = el.checked;
                        } else if (field.type === 'number') {
                            formData[field.id] = el.value ? parseFloat(el.value) : null;
                        } else {
                            formData[field.id] = el.value;
                        }
                    });
                    if (onSubmit) onSubmit(formData);
                });
            }
        }, 0);

        return this;
    }
};
