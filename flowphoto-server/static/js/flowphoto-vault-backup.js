/**
 * FlowVault — локальный зашифрованный бэкап (ключи + upload_claim).
 * Файл .flowvault: PBKDF2 + AES-GCM, расшифровка только паролем бэкапа.
 */
(function (global) {
    'use strict';

    const BACKUP_MAGIC = 'FLOWVAULT_BACKUP';
    const BACKUP_VERSION = 1;
    const PBKDF2_ITERATIONS = 310000;
    const SALT_LENGTH = 16;
    const IV_LENGTH = 12;

    function bytesToBase64Url(bytes) {
        let binary = '';
        const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
        for (let i = 0; i < u8.length; i += 8192) {
            binary += String.fromCharCode.apply(null, u8.subarray(i, i + 8192));
        }
        return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
    }

    function base64UrlToBytes(b64url) {
        let b64 = b64url.replace(/-/g, '+').replace(/_/g, '/');
        while (b64.length % 4) b64 += '=';
        const bin = atob(b64);
        const out = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
        return out;
    }

    async function deriveBackupKey(password, salt) {
        const enc = new TextEncoder();
        const keyMaterial = await crypto.subtle.importKey(
            'raw',
            enc.encode(password),
            'PBKDF2',
            false,
            ['deriveKey'],
        );
        return crypto.subtle.deriveKey(
            { name: 'PBKDF2', salt, iterations: PBKDF2_ITERATIONS, hash: 'SHA-256' },
            keyMaterial,
            { name: 'AES-GCM', length: 256 },
            false,
            ['encrypt', 'decrypt'],
        );
    }

    async function encryptPayload(payload, password) {
        const salt = crypto.getRandomValues(new Uint8Array(SALT_LENGTH));
        const iv = crypto.getRandomValues(new Uint8Array(IV_LENGTH));
        const key = await deriveBackupKey(password, salt);
        const plain = new TextEncoder().encode(JSON.stringify(payload));
        const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, plain);
        return {
            magic: BACKUP_MAGIC,
            version: BACKUP_VERSION,
            kdf: 'PBKDF2-SHA256',
            iterations: PBKDF2_ITERATIONS,
            salt: bytesToBase64Url(salt),
            iv: bytesToBase64Url(iv),
            ciphertext: bytesToBase64Url(new Uint8Array(ciphertext)),
        };
    }

    async function decryptEnvelope(envelope, password) {
        if (!envelope || envelope.magic !== BACKUP_MAGIC) {
            throw new Error('Неверный файл бэкапа FlowVault');
        }
        if (envelope.version !== BACKUP_VERSION) {
            throw new Error('Неподдерживаемая версия бэкапа');
        }
        const salt = base64UrlToBytes(envelope.salt);
        const iv = base64UrlToBytes(envelope.iv);
        const ct = base64UrlToBytes(envelope.ciphertext);
        const key = await deriveBackupKey(password, salt);
        let plain;
        try {
            plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ct);
        } catch (_) {
            throw new Error('Неверный пароль бэкапа');
        }
        const data = JSON.parse(new TextDecoder().decode(plain));
        if (!data || data.version !== BACKUP_VERSION || typeof data.links !== 'object') {
            throw new Error('Повреждённый бэкап');
        }
        return data;
    }

    async function collectBackupPayload() {
        const token = FlowPhotoUpload.getVaultToken();
        if (!token) throw new Error('Сначала войди в FlowVault');

        const photos = await FlowPhotoVault.vaultFetchPhotos();
        const allLinks = FlowPhotoUpload.getVaultLinksMap();
        const links = {};
        let keyed = 0;

        for (const p of photos) {
            const entry = allLinks[p.short_id];
            if (entry?.url && entry.url.includes('#')) {
                links[p.short_id] = {
                    url: entry.url,
                    name: entry.name || p.original_name || '',
                    savedAt: entry.savedAt || Date.now(),
                };
                keyed++;
            }
        }

        if (keyed === 0) {
            throw new Error('Нет ключей для бэкапа — на этом устройстве нечего сохранить');
        }

        const owner = FlowPhotoUpload.getVaultOwner();
        return {
            version: BACKUP_VERSION,
            exported_at: new Date().toISOString(),
            owner: owner?.vault_id && owner?.upload_claim
                ? { vault_id: owner.vault_id, upload_claim: owner.upload_claim }
                : null,
            links,
            meta: {
                vault_photo_count: photos.length,
                keyed_count: keyed,
            },
        };
    }

    function applyBackupPayload(data) {
        const keyed = Object.keys(data.links || {}).length;
        if (!keyed) throw new Error('В бэкапе нет ключей');

        FlowPhotoUpload.importVaultBackupData({
            owner: data.owner || null,
            links: data.links,
        });
        FlowPhotoUpload.clearVaultTokenOnly();
        return {
            keyed,
            hasOwner: !!(data.owner?.vault_id && data.owner?.upload_claim),
            missingOnServer: data.meta?.vault_photo_count
                ? Math.max(0, (data.meta.vault_photo_count || 0) - keyed)
                : 0,
        };
    }

    function backupFilename() {
        const d = new Date();
        const pad = (n) => String(n).padStart(2, '0');
        const stamp = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`;
        return `flowvault-${stamp}.flowvault`;
    }

    async function exportBackupFile(password) {
        if (!password || password.length < 4) {
            throw new Error('Пароль бэкапа — минимум 4 символа');
        }
        const payload = await collectBackupPayload();
        const envelope = await encryptPayload(payload, password);
        const json = JSON.stringify(envelope, null, 2);
        const blob = new Blob([json], { type: 'application/json' });
        const name = backupFilename();

        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = name;
        a.click();
        URL.revokeObjectURL(a.href);

        return {
            filename: name,
            keyed: payload.meta.keyed_count,
            total: payload.meta.vault_photo_count,
            hasOwner: !!payload.owner,
        };
    }

    async function importBackupFile(file, password) {
        if (!file) throw new Error('Выбери файл .flowvault');
        if (!password || password.length < 4) {
            throw new Error('Пароль бэкапа — минимум 4 символа');
        }
        const text = await file.text();
        let envelope;
        try {
            envelope = JSON.parse(text);
        } catch (_) {
            throw new Error('Файл не является бэкапом FlowVault');
        }
        const data = await decryptEnvelope(envelope, password);
        return applyBackupPayload(data);
    }

    global.FlowVaultBackup = {
        exportBackupFile,
        importBackupFile,
        collectBackupPayload,
        BACKUP_VERSION,
    };
})(window);