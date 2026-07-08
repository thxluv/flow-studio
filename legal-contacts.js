/**
 * Flow Studio — контакты для юридических страниц и UI.
 *
 * Чтобы изменить почту или добавить контакт — правь только объект CONTACTS ниже.
 * type: "email" | "url" | "text"
 */
(function (global) {
    'use strict';

    const CONTACTS = {
        /** Общие обращения, privacy, пользователи */
        general: [
            { type: 'email', address: 'hozage@ozvmail.com', label: 'Общие вопросы и персональные данные' },
        ],
        /** Только для уполномоченных государственных органов */
        lawEnforcement: [
            { type: 'email', address: 'hozage@ozvmail.com', label: 'Запросы правоохранительных и иных уполномоченных органов' },
        ],
    };

    const SITE_BASE = 'https://thxluv.github.io/flow-studio/';

    const PAGES = {
        terms: 'terms.html',
        privacy: 'privacy.html',
        lawEnforcement: 'law-enforcement.html',
        index: 'index.html',
    };

    const ACCEPT_STORAGE_KEY = 'flowstudio_legal_accept_v2';

    function pageUrl(name) {
        return SITE_BASE + (PAGES[name] || name);
    }

    function escapeHtml(s) {
        const d = document.createElement('div');
        d.textContent = s || '';
        return d.innerHTML;
    }

    function renderContactEntry(entry) {
        if (!entry) return '';
        if (entry.type === 'email' && entry.address) {
            const label = entry.label ? ` <span class="legal-contact-label">— ${escapeHtml(entry.label)}</span>` : '';
            return `<a href="mailto:${escapeHtml(entry.address)}">${escapeHtml(entry.address)}</a>${label}`;
        }
        if (entry.type === 'url' && entry.address) {
            const label = entry.label ? escapeHtml(entry.label) : escapeHtml(entry.address);
            return `<a href="${escapeHtml(entry.address)}" rel="noopener noreferrer">${label}</a>`;
        }
        if (entry.type === 'text' && entry.label) {
            return escapeHtml(entry.label);
        }
        return '';
    }

    function renderContactList(role) {
        const list = CONTACTS[role] || [];
        if (!list.length) return '<span class="text-slate-500">Контакт не указан</span>';
        return list.map(renderContactEntry).filter(Boolean).join('<br>');
    }

    function primaryEmail(role) {
        const list = CONTACTS[role] || CONTACTS.general || [];
        const mail = list.find((e) => e.type === 'email' && e.address);
        return mail ? mail.address : '';
    }

    function applyContactSlots() {
        document.querySelectorAll('[data-legal-contact]').forEach((el) => {
            el.innerHTML = renderContactList(el.getAttribute('data-legal-contact'));
        });
        document.querySelectorAll('[data-legal-email]').forEach((el) => {
            const role = el.getAttribute('data-legal-email') || 'general';
            const addr = primaryEmail(role);
            if (!addr) return;
            if (el.tagName === 'A') {
                el.href = 'mailto:' + addr;
                if (!el.dataset.legalKeepText) el.textContent = addr;
            } else {
                el.textContent = addr;
            }
        });
    }

    function setBannerVisible(visible) {
        document.body.classList.toggle('legal-banner-visible', !!visible);
    }

    function showAcceptBannerIfNeeded() {
        try {
            if (localStorage.getItem(ACCEPT_STORAGE_KEY)) return;
        } catch (_) { return; }
        const banner = document.getElementById('legal-accept-banner');
        if (!banner) return;
        banner.classList.remove('hidden');
        setBannerVisible(true);
    }

    function acceptLegal() {
        try {
            localStorage.setItem(ACCEPT_STORAGE_KEY, new Date().toISOString());
        } catch (_) { /* ignore */ }
        const banner = document.getElementById('legal-accept-banner');
        if (banner) banner.classList.add('hidden');
        setBannerVisible(false);
    }

    global.FlowLegal = {
        CONTACTS,
        PAGES,
        SITE_BASE,
        pageUrl,
        primaryEmail,
        renderContactList,
        applyContactSlots,
        showAcceptBannerIfNeeded,
        acceptLegal,
        ACCEPT_STORAGE_KEY,
    };

    function boot() {
        applyContactSlots();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})(window);