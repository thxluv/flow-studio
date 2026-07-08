/**
 * Общая логика загрузки FlowPhoto + Vault-сессия (без IP, только localStorage).
 */
(function (global) {
    'use strict';

    const VAULT_TOKEN_KEY = 'fp_vault_token';
    const VAULT_LINKS_KEY = 'fp_vault_links';
    const VAULT_OWNER_KEY = 'fp_vault_owner';
    const VAULT_TRUST_KEY = 'fp_vault_trust';

    let _vaultId = null;
    let _vaultTrust = '';

    function getVaultToken() {
        try { return localStorage.getItem(VAULT_TOKEN_KEY) || ''; } catch (_) { return ''; }
    }

    function setVaultToken(token) {
        try {
            if (token) localStorage.setItem(VAULT_TOKEN_KEY, token);
            else localStorage.removeItem(VAULT_TOKEN_KEY);
        } catch (_) {}
        if (!token) {
            _vaultId = null;
            _vaultTrust = '';
            try { localStorage.removeItem(VAULT_TRUST_KEY); } catch (_) {}
        }
    }

    function getVaultOwner() {
        try {
            const raw = localStorage.getItem(VAULT_OWNER_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch (_) { return null; }
    }

    function setVaultOwner(owner) {
        try {
            if (owner) localStorage.setItem(VAULT_OWNER_KEY, JSON.stringify(owner));
            else localStorage.removeItem(VAULT_OWNER_KEY);
        } catch (_) {}
    }

    function getVaultLinksMap() {
        try {
            const raw = localStorage.getItem(VAULT_LINKS_KEY);
            return raw ? JSON.parse(raw) : {};
        } catch (_) { return {}; }
    }

    function saveVaultLink(shortId, fullUrl, name) {
        try {
            const map = getVaultLinksMap();
            map[shortId] = { url: fullUrl, name: name || '', savedAt: Date.now() };
            localStorage.setItem(VAULT_LINKS_KEY, JSON.stringify(map));
        } catch (_) {}
    }

    function getVaultLink(shortId) {
        const map = getVaultLinksMap();
        return map[shortId]?.url || null;
    }

    function removeVaultLinks(shortIds) {
        try {
            const map = getVaultLinksMap();
            (shortIds || []).forEach(id => { delete map[id]; });
            localStorage.setItem(VAULT_LINKS_KEY, JSON.stringify(map));
        } catch (_) {}
    }

    function importVaultBackupData(data) {
        const incoming = data?.links || {};
        const owner = data?.owner;
        if (owner?.vault_id && owner?.upload_claim) {
            setVaultOwner({ vault_id: owner.vault_id, upload_claim: owner.upload_claim });
            setVaultTrust('owner');
        }
        const merged = { ...getVaultLinksMap(), ...incoming };
        try {
            localStorage.setItem(VAULT_LINKS_KEY, JSON.stringify(merged));
        } catch (_) {
            throw new Error('Не удалось сохранить ключи в браузере');
        }
    }

    function vaultAuthHeaders() {
        const headers = {};
        const token = getVaultToken();
        const owner = getVaultOwner();
        if (token) headers['X-Vault-Token'] = token;
        if (owner?.upload_claim && isVaultOwner()) {
            headers['X-Vault-Upload-Claim'] = owner.upload_claim;
        }
        return headers;
    }

    function setVaultTrust(trust) {
        _vaultTrust = trust;
        try {
            if (trust) localStorage.setItem(VAULT_TRUST_KEY, trust);
            else localStorage.removeItem(VAULT_TRUST_KEY);
        } catch (_) {}
    }

    function hasLocalKeyForPhoto(shortId) {
        const link = getVaultLink(shortId);
        return !!(link && link.includes('#') && link.length > 20);
    }

    async function fetchVaultMe() {
        const token = getVaultToken();
        if (!token) return null;
        const res = await fetch('/api/vault/me', { headers: { 'X-Vault-Token': token } });
        if (!res.ok) return null;
        return res.json();
    }

    async function fetchVaultPhotos() {
        const token = getVaultToken();
        if (!token) return [];
        const res = await fetch('/api/vault/photos', { headers: { 'X-Vault-Token': token } });
        if (res.status === 401) {
            setVaultToken('');
            return [];
        }
        if (!res.ok) return [];
        const data = await res.json();
        return data.photos || [];
    }

    /**
     * owner — есть upload_claim или локальные ключи расшифровки;
     * foreign — вошли в Vault, но ключей на этом устройстве нет.
     */
    async function resolveVaultTrust() {
        const token = getVaultToken();
        if (!token) {
            _vaultId = null;
            if (!getVaultOwner()) setVaultTrust('');
            return localStorage.getItem(VAULT_TRUST_KEY) === 'foreign' ? 'foreign' : '';
        }
        const me = await fetchVaultMe();
        if (!me?.vault_id) {
            setVaultToken('');
            setVaultTrust('');
            return '';
        }
        _vaultId = me.vault_id;
        const owner = getVaultOwner();
        if (owner?.vault_id === me.vault_id && owner?.upload_claim) {
            setVaultTrust('owner');
            return 'owner';
        }
        if (owner?.vault_id && owner.vault_id !== me.vault_id) {
            setVaultTrust('foreign');
            return 'foreign';
        }
        const photos = await fetchVaultPhotos();
        const hasKeys = photos.some(p => hasLocalKeyForPhoto(p.short_id));
        if (hasKeys) {
            setVaultTrust('owner');
            return 'owner';
        }
        setVaultTrust('foreign');
        return 'foreign';
    }

    function applyVaultLogin(data) {
        setVaultToken(data.token);
        if (data.created && data.upload_claim) {
            setVaultOwner({ vault_id: data.vault_id, upload_claim: data.upload_claim });
            setVaultTrust('owner');
            _vaultId = data.vault_id;
        } else {
            const owner = getVaultOwner();
            if (owner?.vault_id === data.vault_id && owner?.upload_claim) {
                setVaultTrust('owner');
                _vaultId = data.vault_id;
            } else {
                setVaultTrust('');
                _vaultId = data.vault_id;
            }
        }
    }

    async function refreshVaultState() {
        if (getVaultToken() && !getVaultOwner() && !localStorage.getItem(VAULT_TRUST_KEY)) {
            return resolveVaultTrust();
        }
        if (getVaultToken()) {
            const cached = localStorage.getItem(VAULT_TRUST_KEY);
            if (cached === 'owner' || cached === 'foreign') {
                _vaultTrust = cached;
                const me = await fetchVaultMe();
                _vaultId = me?.vault_id || null;
                if (_vaultId) {
                    const owner = getVaultOwner();
                    if (owner?.vault_id === _vaultId && owner?.upload_claim) {
                        setVaultTrust('owner');
                        return 'owner';
                    }
                    const photos = await fetchVaultPhotos();
                    if (photos.some(p => hasLocalKeyForPhoto(p.short_id))) {
                        setVaultTrust('owner');
                        return 'owner';
                    }
                }
                if (cached === 'owner') return resolveVaultTrust();
                setVaultTrust('foreign');
                return 'foreign';
            }
        }
        return resolveVaultTrust();
    }

    function isVaultOwner() {
        return _vaultTrust === 'owner' || localStorage.getItem(VAULT_TRUST_KEY) === 'owner';
    }

    function isForeignVault() {
        return _vaultTrust === 'foreign' || localStorage.getItem(VAULT_TRUST_KEY) === 'foreign';
    }

    function canUpload() {
        if (!getVaultToken()) return true;
        return isVaultOwner();
    }

    function clearVaultSession(clearOwner) {
        setVaultToken('');
        setVaultTrust('');
        _vaultId = null;
        if (clearOwner) setVaultOwner(null);
    }

    /** Сброс только токена сессии — ключи и upload_claim в localStorage остаются. */
    function clearVaultTokenOnly() {
        try { localStorage.removeItem(VAULT_TOKEN_KEY); } catch (_) {}
        _vaultId = null;
    }

    /** Имя для сервера — без данных из исходного файла пользователя. */
    function anonymousUploadName(mime) {
        const extByMime = {
            'image/jpeg': 'jpg',
            'image/png': 'png',
            'image/webp': 'webp',
            'image/gif': 'png',
        };
        const ext = extByMime[mime] || 'jpg';
        const rand = (typeof crypto !== 'undefined' && crypto.randomUUID)
            ? crypto.randomUUID().replace(/-/g, '').slice(0, 12)
            : Math.random().toString(36).slice(2, 14);
        return `photo_${rand}.${ext}`;
    }

    async function uploadEncryptedFile(file, options) {
        if (!canUpload()) {
            throw new Error('Чужой FlowVault — создай свой с другим паролем');
        }

        const opts = options || {};
        const stripped = await FlowPhotoCrypto.stripImageMetadata(file);
        const { blob, mime } = stripped;
        const { payload, keyBytes } = await FlowPhotoCrypto.encryptBlob(blob);
        const form = new FormData();
        form.append('encrypted_file', new Blob([payload], { type: 'application/octet-stream' }), 'encrypted.bin');
        form.append('mime_type', mime);
        const storageName = anonymousUploadName(mime);
        form.append('original_name', storageName);
        form.append('retention_seconds', String(opts.retentionSeconds || 2592000));
        form.append('burn_after_read', opts.burnAfterRead ? '1' : '0');
        if (opts.linkPassword) form.append('link_password', opts.linkPassword);

        const headers = {};
        const token = opts.vaultToken || getVaultToken();
        const owner = getVaultOwner();
        if (token && owner?.upload_claim && isVaultOwner()) {
            headers['X-Vault-Token'] = token;
            headers['X-Vault-Upload-Claim'] = owner.upload_claim;
        }

        const res = await fetch('/upload', { method: 'POST', body: form, headers });
        const data = await res.json();
        if (!res.ok) {
            const d = data.detail;
            throw new Error(typeof d === 'string' ? d : (Array.isArray(d) ? d.map(x => x.msg).join(', ') : 'Ошибка загрузки'));
        }

        const fullUrl = FlowPhotoCrypto.buildFullViewUrl(data.short_id, keyBytes);
        if (data.in_vault || (token && isVaultOwner())) saveVaultLink(data.short_id, fullUrl, storageName);
        return { ...data, fullUrl, keyBytes, fileName: storageName };
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

    const FLOWVAULT_NAME = 'FlowVault';

    const VAULT_DISCLAIMER =
        'FlowVault: ключ расшифровки (# в ссылке) хранится только на устройстве того, кто загрузил фото. Чужие снимки в сейфе не открыть — даже при совпадении пароля.';

    global.FlowPhotoUpload = {
        getVaultToken,
        setVaultToken,
        getVaultOwner,
        setVaultOwner,
        saveVaultLink,
        getVaultLink,
        getVaultLinksMap,
        removeVaultLinks,
        importVaultBackupData,
        vaultAuthHeaders,
        applyVaultLogin,
        refreshVaultState,
        resolveVaultTrust,
        isVaultOwner,
        isForeignVault,
        canUpload,
        clearVaultSession,
        clearVaultTokenOnly,
        uploadEncryptedFile,
        renderQr,
        hasLocalKeyForPhoto,
        FLOWVAULT_NAME,
        VAULT_DISCLAIMER,
        VAULT_TOKEN_KEY,
        VAULT_LINKS_KEY,
        VAULT_OWNER_KEY,
    };
})(window);