/**
 * Единый конфиг ссылок Flow Studio (GitHub Pages).
 */
(function () {
    const DEFAULTS = {
        flowNoteUrl: 'https://thxluv.github.io/flow-studio/',
        flowPhotoUrl: 'https://flowphoto.onrender.com',
    };

    window.FLOW_CONFIG = { ...DEFAULTS };
    let configReady = false;

    function normalizeUrl(url, trailingSlash) {
        if (!url || typeof url !== 'string') return '';
        const u = url.trim().replace(/\/$/, '');
        return trailingSlash ? u + '/' : u;
    }

    function applyFlowPhotoLinks() {
        const base = normalizeUrl(window.FLOW_CONFIG.flowPhotoUrl, false);
        document.querySelectorAll('[data-flowphoto-link]').forEach((el) => {
            if (base) {
                el.href = base + '/';
                el.removeAttribute('title');
            } else {
                el.href = 'flowphoto.html';
            }
        });
    }

    function finishConfig(cfg) {
        window.FLOW_CONFIG = { ...DEFAULTS, ...cfg };
        if (cfg.flowNoteUrl) {
            window.FLOW_CONFIG.flowNoteUrl = normalizeUrl(cfg.flowNoteUrl, true);
        }
        const photo = cfg.flowPhotoUrl || DEFAULTS.flowPhotoUrl;
        if (photo) {
            window.FLOW_CONFIG.flowPhotoUrl = normalizeUrl(photo, false);
        }
        configReady = true;
        applyFlowPhotoLinks();
        document.dispatchEvent(new CustomEvent('flow-config-ready', { detail: window.FLOW_CONFIG }));
    }

    fetch('public-config.json', { cache: 'no-store' })
        .then((r) => (r.ok ? r.json() : {}))
        .then(finishConfig)
        .catch(() => finishConfig({}));
})();