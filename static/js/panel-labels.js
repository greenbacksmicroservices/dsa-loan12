(function () {
    const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEXTAREA']);
    const ATTRIBUTES = ['title', 'aria-label', 'placeholder', 'alt'];
    const REPLACEMENTS = [
        [/\bBanking Processing\b/g, 'Bank Login Process'],
        [/\bBank Processing\b/g, 'Bank Login Process'],
        [/\bbanking processing\b/g, 'bank login process'],
        [/\bbank processing\b/g, 'bank login process'],
        [/\bAgents\b/g, 'Channel Partners'],
        [/\bAgent\b/g, 'Channel Partner'],
        [/\bagents\b/g, 'channel partners'],
        [/\bagent\b/g, 'channel partner'],
    ];

    function replaceLabels(value) {
        if (!value) return value;
        return REPLACEMENTS.reduce((text, pair) => text.replace(pair[0], pair[1]), String(value));
    }

    function shouldSkip(node) {
        const parent = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
        return !parent || SKIP_TAGS.has(parent.tagName);
    }

    function normalizeTextNode(node) {
        if (shouldSkip(node)) return;
        const nextValue = replaceLabels(node.nodeValue);
        if (nextValue !== node.nodeValue) {
            node.nodeValue = nextValue;
        }
    }

    function normalizeElementAttributes(element) {
        if (!element || shouldSkip(element)) return;
        ATTRIBUTES.forEach((attr) => {
            if (!element.hasAttribute(attr)) return;
            const current = element.getAttribute(attr);
            const nextValue = replaceLabels(current);
            if (nextValue !== current) {
                element.setAttribute(attr, nextValue);
            }
        });

        const type = String(element.getAttribute('type') || '').toLowerCase();
        if (element.tagName === 'BUTTON' || ['button', 'submit', 'reset'].includes(type)) {
            const current = element.getAttribute('value');
            if (current) {
                const nextValue = replaceLabels(current);
                if (nextValue !== current) {
                    element.setAttribute('value', nextValue);
                }
            }
        }
    }

    function normalizeTree(root) {
        if (!root) return;
        if (root.nodeType === Node.TEXT_NODE) {
            normalizeTextNode(root);
            return;
        }
        if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) {
            return;
        }

        if (root.nodeType === Node.ELEMENT_NODE) {
            normalizeElementAttributes(root);
        }

        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
        let node = walker.nextNode();
        while (node) {
            if (node.nodeType === Node.TEXT_NODE) {
                normalizeTextNode(node);
            } else if (node.nodeType === Node.ELEMENT_NODE) {
                normalizeElementAttributes(node);
            }
            node = walker.nextNode();
        }
    }

    function start() {
        if (document.title) {
            document.title = replaceLabels(document.title);
        }

        if (!window.__panelLabelsDialogPatched) {
            window.__panelLabelsDialogPatched = true;
            const nativeAlert = window.alert;
            const nativeConfirm = window.confirm;
            const nativePrompt = window.prompt;

            window.alert = function (message) {
                return nativeAlert.call(window, replaceLabels(message));
            };
            window.confirm = function (message) {
                return nativeConfirm.call(window, replaceLabels(message));
            };
            window.prompt = function (message, defaultValue) {
                return nativePrompt.call(window, replaceLabels(message), defaultValue);
            };
        }

        normalizeTree(document.body);
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.type === 'characterData') {
                    normalizeTextNode(mutation.target);
                    return;
                }
                mutation.addedNodes.forEach(normalizeTree);
            });
        });
        observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
