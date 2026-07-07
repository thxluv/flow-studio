(function (global) {
    'use strict';

    async function checkPasswordExists(password) {
        const form = new FormData();
        form.append('password', password);
        const res = await fetch('/api/vault/check', { method: 'POST', body: form });
        const data = await res.json();
        return !!data.exists;
    }

    async function vaultLogin(password, intent) {
        const form = new FormData();
        form.append('password', password);
        form.append('intent', intent || 'auto');
        const res = await fetch('/api/vault/login', { method: 'POST', body: form });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Ошибка входа');
        FlowPhotoUpload.applyVaultLogin(data);
        if (!data.created) await FlowPhotoUpload.resolveVaultTrust();
        return data;
    }

    async function vaultFetchPhotos() {
        const token = FlowPhotoUpload.getVaultToken();
        if (!token) return [];
        const res = await fetch('/api/vault/photos', {
            headers: { 'X-Vault-Token': token },
        });
        if (res.status === 401) {
            FlowPhotoUpload.clearVaultSession();
            return [];
        }
        const data = await res.json();
        return data.photos || [];
    }

    function enrichWithLocalLinks(photos) {
        return photos.map(p => ({
            ...p,
            fullUrl: FlowPhotoUpload.getVaultLink(p.short_id),
            hasLocalKey: FlowPhotoUpload.hasLocalKeyForPhoto(p.short_id),
        }));
    }

    global.FlowPhotoVault = {
        checkPasswordExists,
        vaultLogin,
        vaultFetchPhotos,
        enrichWithLocalLinks,
    };
})(window);