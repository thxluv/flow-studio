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
            FlowPhotoUpload.clearVaultSession(true);
            return [];
        }
        const data = await res.json();
        return data.photos || [];
    }

    async function vaultDeletePhoto(shortId) {
        const res = await fetch('/api/vault/photos/' + shortId, {
            method: 'DELETE',
            headers: FlowPhotoUpload.vaultAuthHeaders(),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'Не удалось удалить');
        FlowPhotoUpload.removeVaultLinks([shortId]);
        return data;
    }

    async function vaultDeleteBatch(shortIds) {
        const form = new FormData();
        form.append('short_ids', shortIds.join(','));
        const res = await fetch('/api/vault/photos/delete-batch', {
            method: 'POST',
            body: form,
            headers: FlowPhotoUpload.vaultAuthHeaders(),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'Не удалось удалить');
        FlowPhotoUpload.removeVaultLinks(shortIds);
        return data;
    }

    async function vaultBurnAll() {
        const res = await fetch('/api/vault/burn-all', {
            method: 'POST',
            headers: FlowPhotoUpload.vaultAuthHeaders(),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'Не удалось сжечь');
        return data;
    }

    async function vaultDeleteAccount(password) {
        const form = new FormData();
        form.append('password', password);
        const res = await fetch('/api/vault/account', {
            method: 'DELETE',
            body: form,
            headers: FlowPhotoUpload.vaultAuthHeaders(),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || 'Не удалось удалить аккаунт');
        FlowPhotoUpload.clearVaultSession(true);
        return data;
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
        vaultDeletePhoto,
        vaultDeleteBatch,
        vaultBurnAll,
        vaultDeleteAccount,
        enrichWithLocalLinks,
    };
})(window);