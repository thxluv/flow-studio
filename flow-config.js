/**
 * Единый конфиг ссылок Flow Studio (GitHub Pages).
 * public-config.json обновляется после деплоя FlowPhoto в облако.
 */
(function () {
    const DEFAULTS = {
        flowNoteUrl: 'https://thxluv.github.io/flow-studio/',
        flowPhotoUrl: '',
    };

    window.FLOW_CONFIG = { ...DEFAULTS };

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
                el.title = 'FlowPhoto: укажи flowPhotoUrl в public-config.json';
            }
        });
    }

    fetch('public-config.json', { cache: 'no-store' })
        .then((r) => (r.ok ? r.json() : {}))
        .then((cfg) => {
            window.FLOW_CONFIG = { ...DEFAULTS, ...cfg };
            if (cfg.flowNoteUrl) {
                window.FLOW_CONFIG.flowNoteUrl = normalizeUrl(cfg.flowNoteUrl, true);
            }
            if (cfg.flowPhotoUrl) {
                window.FLOW_CONFIG.flowPhotoUrl = normalizeUrl(cfg.flowPhotoUrl, false);
            }
            applyFlowPhotoLinks();
            document.dispatchEvent(new CustomEvent('flow-config-ready', { detail: window.FLOW_CONFIG }));
        })
        .catch(() => applyFlowPhotoLinks());
})();