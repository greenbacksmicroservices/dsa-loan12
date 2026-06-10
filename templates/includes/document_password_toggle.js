function bindDocumentPasswordToggle(scope) {
    const root = scope || document;
    root.querySelectorAll('.document-password-wrap, .document-item').forEach((item) => {
        const checkbox = item.querySelector('.document-has-password');
        const passwordInput = item.querySelector('.document-password-input');
        const enabledInput = item.querySelector('.document-password-enabled');
        const inputWrap = item.querySelector('.document-password-input-wrap');
        const visibilityBtn = item.querySelector('.document-password-visibility-btn');

        if (checkbox && passwordInput && checkbox.dataset.bound !== '1') {
            checkbox.dataset.bound = '1';
            checkbox.addEventListener('change', function () {
                const show = checkbox.checked;
                if (inputWrap) {
                    inputWrap.style.display = show ? 'block' : 'none';
                } else {
                    passwordInput.style.display = show ? 'block' : 'none';
                }
                if (enabledInput) enabledInput.value = show ? '1' : '0';
                if (!show) {
                    passwordInput.value = '';
                    passwordInput.type = 'password';
                    if (visibilityBtn) visibilityBtn.textContent = 'Show';
                }
            });
        }

        if (visibilityBtn && passwordInput && visibilityBtn.dataset.bound !== '1') {
            visibilityBtn.dataset.bound = '1';
            visibilityBtn.addEventListener('click', function () {
                const isHidden = passwordInput.type === 'password';
                passwordInput.type = isHidden ? 'text' : 'password';
                visibilityBtn.textContent = isHidden ? 'Hide' : 'Show';
            });
        }
    });
}
