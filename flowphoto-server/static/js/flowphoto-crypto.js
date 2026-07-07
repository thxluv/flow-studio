/**
 * FlowPhoto — клиентское шифрование (Web Crypto API, AES-GCM 256 бит).
 * Ключ никогда не отправляется на сервер — только в hash ссылки (#...).
 */
(function (global) {
    'use strict';

    const IV_LENGTH = 12;
    const KEY_LENGTH = 32;

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

    async function importAesKey(rawKey) {
        return crypto.subtle.importKey('raw', rawKey, { name: 'AES-GCM', length: 256 }, false, [
            'encrypt',
            'decrypt',
        ]);
    }

    /**
     * Удаляет EXIF: перерисовка через canvas (метаданные не попадают в ciphertext).
     */
    async function stripImageMetadata(file) {
        const url = URL.createObjectURL(file);
        try {
            const img = await new Promise((resolve, reject) => {
                const el = new Image();
                el.onload = () => resolve(el);
                el.onerror = () => reject(new Error('Не удалось прочитать изображение'));
                el.src = url;
            });
            const canvas = document.createElement('canvas');
            canvas.width = img.naturalWidth;
            canvas.height = img.naturalHeight;
            canvas.getContext('2d').drawImage(img, 0, 0);
            const mime = file.type === 'image/png' ? 'image/png' : 'image/jpeg';
            const quality = mime === 'image/jpeg' ? 0.92 : undefined;
            const blob = await new Promise((res, rej) => {
                canvas.toBlob((b) => (b ? res(b) : rej(new Error('Ошибка перекодирования'))), mime, quality);
            });
            return { blob, mime, width: img.naturalWidth, height: img.naturalHeight };
        } finally {
            URL.revokeObjectURL(url);
        }
    }

    /**
     * Шифрует blob → Uint8Array: [IV 12 байт][ciphertext+tag]
     * Возвращает { payload, keyBytes } — keyBytes для hash ссылки.
     */
    async function encryptBlob(blob) {
        const raw = await blob.arrayBuffer();
        const keyBytes = crypto.getRandomValues(new Uint8Array(KEY_LENGTH));
        const iv = crypto.getRandomValues(new Uint8Array(IV_LENGTH));
        const key = await importAesKey(keyBytes);
        const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, raw);
        const payload = new Uint8Array(iv.length + ciphertext.byteLength);
        payload.set(iv, 0);
        payload.set(new Uint8Array(ciphertext), iv.length);
        return { payload, keyBytes };
    }

    /**
     * Расшифровка blob с сервера (первые 12 байт — IV).
     */
    async function decryptPayload(encryptedBuffer, keyB64Url) {
        const keyBytes = base64UrlToBytes(keyB64Url);
        if (keyBytes.length !== KEY_LENGTH) {
            throw new Error('Неверная длина ключа в ссылке');
        }
        const data = new Uint8Array(encryptedBuffer);
        if (data.length < IV_LENGTH + 1) {
            throw new Error('Повреждённый файл');
        }
        const iv = data.slice(0, IV_LENGTH);
        const ct = data.slice(IV_LENGTH);
        const key = await importAesKey(keyBytes);
        const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ct);
        return plain;
    }

    function buildFullViewUrl(shortId, keyBytes) {
        const keyPart = bytesToBase64Url(keyBytes);
        const base = `${location.origin}/view/${shortId}`;
        return `${base}#${keyPart}`;
    }

    function getKeyFromHash() {
        const hash = location.hash.replace(/^#/, '').trim();
        return hash || null;
    }

    global.FlowPhotoCrypto = {
        stripImageMetadata,
        encryptBlob,
        decryptPayload,
        buildFullViewUrl,
        getKeyFromHash,
        bytesToBase64Url,
        IV_LENGTH,
        KEY_LENGTH,
    };
})(window);