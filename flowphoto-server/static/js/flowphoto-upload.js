/**
 * Общая логика загрузки FlowPhoto (главная + ответ с view).
 */
(function (global) {
    'use strict';

    const VAULT_TOKEN_KEY = 'fp_vault_token';
    const VAULT_LINKS_KEY = 'fp_vault_links';

    function getVaultToken() {
        try { return localStorage.getItem(VAULT_TOKEN_KEY) || ''; } catch (_) { return ''; }
    }

    function setVaultToken(token) {
        try {
            if (token) localStorage.setItem(VAULT_TOKEN_KEY, token);
            else localStorage.removeItem(VAULT_TOKEN_KEY);
        } catch (_) {}
    }

    function saveVaultLink(shortId, fullUrl, name) {
        try {
            const raw = localStorage.getItem(VAULT_LINKS_KEY);
            const map = raw ? JSON.parse(raw) : {};
            map[shortId] = { url: fullUrl, name: name || '', savedAt: Date.now() };
            localStorage.setItem(VAULT_LINKS_KEY, JSON.stringify(map));
        } catch (_) {}
    }

    function getVaultLink(shortId) {
        try {
            const raw = localStorage.getItem(VAULT_LINKS_KEY);
            const map = raw ? JSON.parse(raw) : {};
            return map[shortId]?.url || null;
        } catch (_) { return null; }
    }

    async function uploadEncryptedFile(file, options) {
        const opts = options || {};
        const { blob, mime } = await FlowPhotoCrypto.stripImageMetadata(file);
        const { payload, keyBytes } = await FlowPhotoCrypto.encryptBlob(blob);
        const form = new FormData();
        form.append('encrypted_file', new Blob([payload], { type: 'application/octet-stream' }), 'encrypted.bin');
        form.append('mime_type', mime);
        form.append('original_name', file.name);
        form.append('retention_seconds', String(opts.retentionSeconds || 2592000));
        form.append('burn_after_read', opts.burnAfterRead ? '1' : '0');
        if (opts.linkPassword) form.append('link_password', opts.linkPassword);

        const headers = {};
        const token = opts.vaultToken || getVaultToken();
        if (token) headers['X-Vault-Token'] = token;

        const res = await fetch('/upload', { method: 'POST', body: form, headers });
        const data = await res.json();
        if (!res.ok) {
            const d = data.detail;
            throw new Error(typeof d === 'string' ? d : (Array.isArray(d) ? d.map(x => x.msg).join(', ') : 'Ошибка загрузки'));
        }

        const fullUrl = FlowPhotoCrypto.buildFullViewUrl(data.short_id, keyBytes);
        if (token || data.in_vault) saveVaultLink(data.short_id, fullUrl, file.name);
        return { ...data, fullUrl, keyBytes, fileName: file.name };
    }

    function renderQr(canvasOrId, url) {
        const el = typeof canvasOrId === 'string' ? document.getElementById(canvasOrId) : canvasOrId;
        if (!el || !global.QRCode) return;
        el.innerHTML = '';
        global.QRCode.toCanvas(el, url, {
            width: Math.min(180, window.innerWidth - 80),
            margin: 1,
            color: { dark: '#c4b5fd', light: '#00000000' },
        }, () => {});
    }

    global.FlowPhotoUpload = {
        getVaultToken,
        setVaultToken,
        saveVaultLink,
        getVaultLink,
        uploadEncryptedFile,
        renderQr,
        VAULT_TOKEN_KEY,
        VAULT_LINKS_KEY,
    };
})(window);