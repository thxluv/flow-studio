/**
 * FlowPhoto Host — локальный сервер на ноуте
 * Принимает зашифрованный пакет, кладёт в flowphoto-storage/, пушит в GitHub.
 * Запуск: node server.js   или   start-host.bat
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const PORT = Number(process.env.FLOWPHOTO_PORT) || 8787;
const PROJECT_ROOT = path.join(__dirname, '..');
const STORAGE_DIR = path.join(PROJECT_ROOT, 'flowphoto-storage');
const SLUG_RE = /^[A-Za-z0-9]{10,24}$/;

if (!fs.existsSync(STORAGE_DIR)) fs.mkdirSync(STORAGE_DIR, { recursive: true });

const CORS_ORIGINS = [
    'https://thxluv.github.io',
    'http://localhost',
    'http://127.0.0.1',
    'null'
];

function corsHeaders(origin) {
    const allowed = !origin || CORS_ORIGINS.some(o => origin.startsWith(o)) || origin.includes('github.io');
    return {
        'Access-Control-Allow-Origin': allowed ? (origin || '*') : 'https://thxluv.github.io',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Max-Age': '86400'
    };
}

function readBody(req) {
    return new Promise((resolve, reject) => {
        const chunks = [];
        let size = 0;
        req.on('data', chunk => {
            size += chunk.length;
            if (size > 25 * 1024 * 1024) {
                reject(new Error('Payload too large'));
                req.destroy();
                return;
            }
            chunks.push(chunk);
        });
        req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
        req.on('error', reject);
    });
}

function gitPush(slug) {
    const rel = `flowphoto-storage/${slug}.json`;
    try {
        execSync(`git add "${rel}"`, { cwd: PROJECT_ROOT, stdio: 'pipe' });
        const status = execSync('git status --porcelain', { cwd: PROJECT_ROOT, encoding: 'utf8' });
        if (!status.trim()) return { pushed: false, message: 'Уже в git' };
        execSync(`git commit -m "flowphoto: ${slug}"`, { cwd: PROJECT_ROOT, stdio: 'pipe' });
        execSync('git push origin main', { cwd: PROJECT_ROOT, stdio: 'pipe', timeout: 120000 });
        return { pushed: true, message: 'Залито на GitHub' };
    } catch (e) {
        return { pushed: false, message: (e.stderr || e.message || '').toString().slice(0, 200) };
    }
}

function savePackage(slug, pkg) {
    const file = path.join(STORAGE_DIR, `${slug}.json`);
    fs.writeFileSync(file, JSON.stringify(pkg, null, 2), 'utf8');
    return file;
}

const server = http.createServer(async (req, res) => {
    const origin = req.headers.origin || '';
    const headers = { 'Content-Type': 'application/json; charset=utf-8', ...corsHeaders(origin) };

    if (req.method === 'OPTIONS') {
        res.writeHead(204, headers);
        res.end();
        return;
    }

    try {
        if (req.method === 'GET' && req.url === '/api/health') {
            res.writeHead(200, headers);
            res.end(JSON.stringify({
                ok: true,
                service: 'flowphoto-host',
                storage: STORAGE_DIR,
                github: 'flowphoto-storage/*.json → git push'
            }));
            return;
        }

        if (req.method === 'GET' && req.url.startsWith('/storage/')) {
            const slug = req.url.slice('/storage/'.length).replace(/\.json$/, '');
            if (!SLUG_RE.test(slug)) {
                res.writeHead(400, headers);
                res.end(JSON.stringify({ error: 'Invalid slug' }));
                return;
            }
            const file = path.join(STORAGE_DIR, `${slug}.json`);
            if (!fs.existsSync(file)) {
                res.writeHead(404, headers);
                res.end(JSON.stringify({ error: 'Not found' }));
                return;
            }
            res.writeHead(200, { ...headers, 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
            res.end(fs.readFileSync(file, 'utf8'));
            return;
        }

        if (req.method === 'POST' && req.url === '/api/upload') {
            const raw = await readBody(req);
            const body = JSON.parse(raw);
            const pkg = body.package;
            let slug = body.slug;
            const pushGit = body.pushGit !== false;

            if (!pkg || pkg.format !== 'flowphoto-v1') {
                res.writeHead(400, headers);
                res.end(JSON.stringify({ error: 'Invalid package' }));
                return;
            }
            slug = slug || pkg.meta?.serverSlug;
            if (!slug || !SLUG_RE.test(slug)) {
                res.writeHead(400, headers);
                res.end(JSON.stringify({ error: 'Invalid slug' }));
                return;
            }

            savePackage(slug, pkg);
            const git = pushGit ? gitPush(slug) : { pushed: false, message: 'Git push skipped' };

            res.writeHead(200, headers);
            res.end(JSON.stringify({
                ok: true,
                slug,
                localUrl: `http://127.0.0.1:${PORT}/storage/${slug}.json`,
                githubRawUrl: `https://raw.githubusercontent.com/thxluv/flow-studio/main/flowphoto-storage/${slug}.json`,
                git
            }));
            return;
        }

        res.writeHead(404, headers);
        res.end(JSON.stringify({ error: 'Not found' }));
    } catch (e) {
        res.writeHead(500, headers);
        res.end(JSON.stringify({ error: e.message || 'Server error' }));
    }
});

server.listen(PORT, '127.0.0.1', () => {
    console.log('');
    console.log('  FlowPhoto Host запущен');
    console.log(`  http://127.0.0.1:${PORT}/api/health`);
    console.log('  Загрузка: POST /api/upload');
    console.log('  Чтение:   GET  /storage/{slug}.json');
    console.log('');
    console.log('  Оставь окно открытым при загрузке фото с сайта.');
    console.log('  Ctrl+C — остановить');
    console.log('');
});