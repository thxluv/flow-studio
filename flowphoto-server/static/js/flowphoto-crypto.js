/**
 * FlowPhoto — клиентское шифрование (Web Crypto API, AES-GCM 256 бит).
 * Ключ никогда не отправляется на сервер — только в hash ссылки (#...).
 */
(function (global) {
    'use strict';

    const IV_LENGTH = 12;
    const KEY_LENGTH = 32;
    const MAX_CANVAS_DIM = 8192;

    const STRIPPABLE_IMAGE_TYPES = new Set([
        'image/jpeg',
        'image/jpg',
        'image/png',
        'image/webp',
        'image/gif',
        'image/bmp',
        'image/avif',
    ]);

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

    function normalizeImageType(type) {
        const t = (type || '').toLowerCase();
        return t === 'image/jpg' ? 'image/jpeg' : t;
    }

    function isStrippableImage(file) {
        const type = normalizeImageType(file?.type);
        return STRIPPABLE_IMAGE_TYPES.has(type) || type.startsWith('image/');
    }

    function outputMimeFor(type) {
        const t = normalizeImageType(type);
        if (t === 'image/png') return 'image/png';
        if (t === 'image/webp') return 'image/webp';
        if (t === 'image/gif') return 'image/png';
        return 'image/jpeg';
    }

    let _webpEncodeSupported = null;

    async function canEncodeWebp() {
        if (_webpEncodeSupported !== null) return _webpEncodeSupported;
        if (typeof document === 'undefined') return false;
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = 1;
        _webpEncodeSupported = await new Promise((resolve) => {
            canvas.toBlob((blob) => resolve(!!blob), 'image/webp', 0.8);
        });
        return _webpEncodeSupported;
    }

    function fitDimensions(width, height, maxDim) {
        if (width <= maxDim && height <= maxDim) {
            return { width, height, scale: 1 };
        }
        const scale = Math.min(maxDim / width, maxDim / height);
        return {
            width: Math.max(1, Math.round(width * scale)),
            height: Math.max(1, Math.round(height * scale)),
            scale,
        };
    }

    async function loadImageSource(file) {
        if (typeof createImageBitmap === 'function') {
            try {
                const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
                return { kind: 'bitmap', bitmap };
            } catch (_) {
                /* fallback ниже */
            }
        }

        const url = URL.createObjectURL(file);
        try {
            const img = await new Promise((resolve, reject) => {
                const el = new Image();
                el.onload = () => resolve(el);
                el.onerror = () => reject(new Error('Не удалось прочитать изображение'));
                el.src = url;
            });
            return { kind: 'image', image: img };
        } finally {
            URL.revokeObjectURL(url);
        }
    }

    function drawSourceToCanvas(source, targetWidth, targetHeight, outputMime) {
        const canvas = document.createElement('canvas');
        canvas.width = targetWidth;
        canvas.height = targetHeight;
        const ctx = canvas.getContext('2d', { alpha: true });
        if (!ctx) throw new Error('Canvas недоступен');

        if (outputMime === 'image/jpeg') {
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, targetWidth, targetHeight);
        }
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';

        if (source.kind === 'bitmap') {
            ctx.drawImage(source.bitmap, 0, 0, targetWidth, targetHeight);
            if (typeof source.bitmap.close === 'function') source.bitmap.close();
        } else {
            ctx.drawImage(source.image, 0, 0, targetWidth, targetHeight);
        }

        return canvas;
    }

    async function encodeCanvas(canvas, mime) {
        const quality = mime === 'image/jpeg' ? 0.92 : mime === 'image/webp' ? 0.9 : undefined;
        const blob = await new Promise((resolve, reject) => {
            canvas.toBlob(
                (b) => (b ? resolve(b) : reject(new Error('Ошибка перекодирования изображения'))),
                mime,
                quality
            );
        });
        return blob;
    }

    /**
     * Удаляет EXIF/IPTC/XMP и прочие метаданные: декод → canvas → новый файл.
     * Ориентация из EXIF применяется, но в выходной файл не записывается.
     */
    async function stripImageMetadata(file) {
        const inputType = normalizeImageType(file?.type);
        if (!isStrippableImage(file)) {
            throw new Error('Поддерживаются только изображения (JPG, PNG, WebP, GIF)');
        }

        const source = await loadImageSource(file);
        const naturalWidth = source.kind === 'bitmap' ? source.bitmap.width : source.image.naturalWidth;
        const naturalHeight = source.kind === 'bitmap' ? source.bitmap.height : source.image.naturalHeight;

        if (!naturalWidth || !naturalHeight) {
            throw new Error('Пустое или повреждённое изображение');
        }

        const fitted = fitDimensions(naturalWidth, naturalHeight, MAX_CANVAS_DIM);
        let mime = outputMimeFor(inputType);
        if (mime === 'image/webp' && !(await canEncodeWebp())) {
            mime = 'image/jpeg';
        }

        const canvas = drawSourceToCanvas(source, fitted.width, fitted.height, mime);
        const blob = await encodeCanvas(canvas, mime);

        return {
            blob,
            mime,
            width: fitted.width,
            height: fitted.height,
            metadataStripped: true,
            resized: fitted.scale < 1,
        };
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
        isStrippableImage,
        encryptBlob,
        decryptPayload,
        buildFullViewUrl,
        getKeyFromHash,
        bytesToBase64Url,
        IV_LENGTH,
        KEY_LENGTH,
    };
})(window);