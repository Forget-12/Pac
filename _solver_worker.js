


// _solver_worker.js — Solver child process for pandax9.py
// 1x browser (di-recycle saat idle), context.close() tiap task → RAM tidak menumpuk.
// Protokol NDJSON stdin/stdout identik dengan versi sebelumnya.
const { connect } = require("puppeteer-real-browser");
const fs = require("fs");
const path = require("path");
const readline = require("readline");

const CONFIG_FILE      = process.env.BOT_CONFIG_FILE || "";
// bot_config.json dibaca ulang tiap kali & hanya jika mtime berubah → hot-reload tanpa restart.
// JSON rusak saat diketik/di-save → pertahankan konfigurasi lama, jangan crash.
let _cfgCache = { mtime: 0, data: {} };
function cfgNum(key, def) {
    if (!CONFIG_FILE) return def;
    try {
        const st = fs.statSync(CONFIG_FILE);
        if (st.mtimeMs !== _cfgCache.mtime) {
            let data = null;
            try { data = JSON.parse(fs.readFileSync(CONFIG_FILE, "utf8")); } catch (e) { data = null; }
            if (data && typeof data === "object") _cfgCache.data = data;
            _cfgCache.mtime = st.mtimeMs;
        }
        const v = Number(_cfgCache.data[key]);
        return (Number.isFinite(v) && v > 0) ? v : def;
    } catch (e) { return def; }
}
let lastMaxActive = -1, lastMaxQueue = -1, lastTaskTimeout = -1;
function getMaxActive()  { const v = cfgNum("solver_max_active", parseInt(process.env.MAX_ACTIVE, 10)    || 1);      if (v !== lastMaxActive)  { lastMaxActive  = v; logMsg(`[CFG] MAX_ACTIVE=${v} (hot-reload)`); }  return v; }
function getMaxQueue()   { const v = cfgNum("solver_max_queue",  parseInt(process.env.MAX_QUEUE, 10)     || 6);      if (v !== lastMaxQueue)   { lastMaxQueue   = v; logMsg(`[CFG] MAX_QUEUE=${v} (hot-reload)`); }   return v; }
function getTaskTimeout(){ const v = cfgNum("task_timeout",      parseInt(process.env.TASK_TIMEOUT, 10)  || 120000); if (v !== lastTaskTimeout){ lastTaskTimeout= v; logMsg(`[CFG] TASK_TIMEOUT=${v} (hot-reload)`); } return v; }
const CHROME_PATH      = process.env.CHROME_PATH || "/usr/bin/chromium";
const IDLE_RECYCLE_MS  = parseInt(process.env.BROWSER_IDLE_RECYCLE_MS || "600000", 10); // 0 = nonaktif
const RECYCLE_EVERY_TASKS = parseInt(process.env.RECYCLE_EVERY_TASKS || "10", 10);  // recycle Chromium tiap N task; 0 = nonaktif
const BLOCK_SUBRES     = process.env.BLOCK_SUBRESOURCES !== "0"; // blok image/media/font (hemat RAM+bandwidth)
const TMP_MAX_AGE_MS   = 3600 * 1000; // folder sisa lebih muda dari 1 jam dibiarkan (bisa milik proses lain)

let browser = null;
let browserStarting = null;
let browserAlive = false;
let browserGen = 0;
let activeTasks = 0;
let tasksDone = 0;
let pendingRecycle = false;
let shuttingDown = false;
let idleTimer = null;
const queue = [];
const running = new Map(); // id -> { page, context, signal }

function send(obj) {
    process.stdout.write(JSON.stringify(obj) + "\n");
}
function logMsg(msg) {
    process.stderr.write(msg + "\n");
}

process.on("unhandledRejection", (e) => {
    logMsg("[FATAL] unhandledRejection: " + (e && (e.stack || e.message) || String(e)));
});

// ---------- validasi target (anti SSRF / navigasi ke jaringan internal) ----------
function blockedHost(hostname) {
    const h = String(hostname || "").toLowerCase();
    if (!h) return true;
    if (h === "localhost" || h.endsWith(".local") || h.endsWith(".internal") || h === "metadata.google.internal") return true;
    const m = h.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
    if (m) {
        const a = +m[1], b = +m[2];
        if (a === 0 || a === 10 || a === 127) return true;
        if (a === 169 && b === 254) return true;      // link-local + cloud metadata
        if (a === 192 && b === 168) return true;
        if (a === 172 && b >= 16 && b <= 31) return true;
    }
    if (h === "::1" || h.startsWith("fe80:") || h.startsWith("fc") || h.startsWith("fd") || h.startsWith("[::")) return true;
    return false;
}
function validateDomain(domain) {
    let u;
    try { u = new URL(domain); } catch { return null; }
    if (u.protocol !== "https:" && u.protocol !== "http:") return null;
    if (blockedHost(u.hostname)) return null;
    return u;
}

// ---------- browser lifecycle (idle recycle → bebaskan RAM baseline) ----------
function scheduleIdleRecycle() {
    if (!IDLE_RECYCLE_MS) return;
    clearTimeout(idleTimer);
    idleTimer = setTimeout(async () => {
        if (activeTasks === 0 && queue.length === 0 && browser) {
            logMsg("[BROWSER] Idle — recycle Chromium (hemat RAM).");
            const b = browser;
            browser = null;
            browserAlive = false;
            browserGen++;
            try { await b.close(); } catch (e) { logMsg("[BROWSER] close: " + (e && e.message)); }
        }
    }, IDLE_RECYCLE_MS);
    idleTimer.unref?.();
}

async function launchBrowser() {
    logMsg("[BROWSER] Meluncurkan Chromium...");
    const gen = ++browserGen;
    const started = connect({
        headless: false,
        turnstile: true,
        customConfig: {
            chromePath: CHROME_PATH,
            args: [
                '--no-sandbox',
                '--disable-gpu',
                '--disable-dev-shm-usage',
                '--js-flags=--max-old-space-size=512',
                '--disable-background-networking',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-component-update',
                '--disable-default-apps',
                '--disable-extensions',
                '--disable-sync',
                '--disable-breakpad',
                '--no-first-run',
                '--no-default-browser-check',
                '--mute-audio',
                '--disk-cache-size=10485760'
            ]
        }
    }).then(ctx => {
        if (gen !== browserGen) { // sudah di-recycle/diganti sebelum connect selesai
            try { ctx.browser.close(); } catch {}
            throw new Error("launch superseded");
        }
        browser = ctx.browser;
        browserAlive = true;
        logMsg("[BROWSER] Chromium berhasil diluncurkan!");
        browser.on("disconnected", () => {
            if (gen !== browserGen) return; // event dari generasi lama
            logMsg("[BROWSER] Chromium putus koneksi — akan diluncurkan ulang saat task berikutnya.");
            browser = null;
            browserAlive = false;
            for (const entry of running.values()) entry.signal.aborted = true;
        });
        return browser;
    }).catch(err => {
        throw new Error("Launch failed: " + err.message);
    });
    return started;
}

async function init_browser() {
    if (!browser || !browserAlive) {
        if (!browserStarting) {
            browserStarting = launchBrowser()
                .catch(err => { throw err; })
                .finally(() => { browserStarting = null; });
        }
        await browserStarting;
    }
    const context = await browser.createBrowserContext();
    const page = await context.newPage();
    page.setDefaultNavigationTimeout(getTaskTimeout());
    page.setDefaultTimeout(getTaskTimeout());
    return { page, context };
}

// -------- turnstile.js logic (dioptimalkan) --------
async function turnstile({ domain, siteKey, action, cdata, pagedata }, page, signal) {
    const timeout = getTaskTimeout();
    const startTime = Date.now();
    let targetHost = domain;
    try { targetHost = new URL(domain).hostname; } catch (e) {}

    // JSON.stringify → kebal terhadap kutip/</script> di nilai cdata/pagedata
    const esc = (v) => JSON.stringify(String(v == null ? "" : v));

    const htmlContent = `
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Verification</title>
                <style>
                    body {
                        margin: 0; padding: 0; display: flex; justify-content: center; align-items: center; height: 100vh; background-color: #f9f9f9;
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                    }
                    #cf-container { margin: auto; }
                </style>
            </head>
            <body>
                <div id="cf-container" class="cf-turnstile"></div>
                <script>
                    window.__cfError = null;
                    window.__cfToken = null;
                    window.onloadTurnstileCallback = function () {
                        try {
                            turnstile.render('#cf-container', {
                                sitekey: ${esc(siteKey)},
                                ${action ? `action: ${esc(action)},` : ""}
                                ${cdata ? `cData: ${esc(cdata)},` : ""}
                                ${pagedata ? `chlPageData: ${esc(pagedata)},` : ""}
                                callback: function (token) {
                                    window.__cfToken = token;
                                    var c = document.createElement('input');
                                    c.type = 'hidden';
                                    c.name = 'cf-response';
                                    c.value = token;
                                    document.body.appendChild(c);
                                },
                                'error-callback': function(code) {
                                    window.__cfError = code;
                                },
                                'expired-callback': function() {
                                    window.__cfToken = null;
                                }
                            });
                        } catch(e) {
                            window.__cfError = 'render_err: ' + e.message;
                        }
                    };
                </script>
                <script src="https://challenges.cloudflare.com/turnstile/v0/api.js?onload=onloadTurnstileCallback" defer></script>
            </body>
            </html>
        `;

    await page.setRequestInterception(true);

    let intercepted = false;
    const onRequest = async (request) => {
        try {
            const rt = request.resourceType();
            // Hemat RAM/bandwidth: widget tidak butuh gambar/media/font
            if (BLOCK_SUBRES && (rt === "image" || rt === "media" || rt === "font")) {
                await request.abort();
                return;
            }
            if (!intercepted && request.isNavigationRequest() && request.frame() === page.mainFrame()) {
                try {
                    await request.respond({
                        status: 200,
                        contentType: "text/html",
                        body: htmlContent
                    });
                    intercepted = true; // hanya set setelah respond sukses
                } catch (e) {
                    logMsg("[ts] Intercept respond gagal: " + (e && e.message));
                }
                return;
            }
            await request.continue();
        } catch (e) {
            logMsg("[ts] request handler: " + (e && e.message));
        }
    };
    page.on("request", onRequest);

    try {
        logMsg(`[ts] Navigasi ke: ${domain}`);
        // Gagal navigasi = error instan (bukan tunggu 120 detik polling)
        await page.goto(domain, { waitUntil: "domcontentloaded", timeout });

        let lastLogSec = -1;
        let nextClickAt = Date.now() + 3000 + Math.random() * 2000;
        let interval = 800; // backoff 800ms → 2000ms

        while (Date.now() - startTime < timeout) {
            if (signal.aborted) throw new Error("cancelled");

            const token = await page.evaluate(() => {
                return window.__cfToken ||
                       document.querySelector('[name="cf-response"]')?.value ||
                       document.querySelector('input[name="cf-turnstile-response"]')?.value;
            }).catch(() => null);

            if (token && token.length > 10) {
                logMsg(`[ts] Token didapat (${token.length} chars)`);
                return { token, type: "turnstile" };
            }

            const errCode = await page.evaluate(() => window.__cfError).catch(() => null);
            if (errCode) {
                if (String(errCode).includes('300030')) {
                    throw new Error(`Invalid Sitekey (300030) untuk domain ${targetHost}`);
                }
                if (String(errCode).includes('600010')) {
                    throw new Error(`Bot detected (600010)`);
                }
                throw new Error(`Widget error code: ${errCode}`);
            }

            const elapsed = Math.floor((Date.now() - startTime) / 1000);
            if (elapsed % 5 === 0 && elapsed > 0 && elapsed !== lastLogSec) {
                lastLogSec = elapsed;
                logMsg(`[ts] Menunggu token... (${elapsed}s)`);
            }

            // Klik checkbox widget — posisi & interval di-jitter (anti pola bot)
            if (elapsed >= 3 && Date.now() >= nextClickAt) {
                try {
                    const iframes = await page.$$('iframe');
                    for (const frameElement of iframes) {
                        const src = await frameElement.evaluate(el => el.src).catch(() => "");
                        if (src.includes("challenges.cloudflare.com")) {
                            const box = await frameElement.boundingBox().catch(() => null);
                            if (box && box.width > 0 && box.height > 0) {
                                const cx = box.x + box.width * (0.3 + Math.random() * 0.4);
                                const cy = box.y + box.height * (0.3 + Math.random() * 0.4);
                                await page.mouse.move(cx, cy, { steps: 4 + Math.floor(Math.random() * 5) }).catch(() => {});
                                await page.mouse.down().catch(() => {});
                                await new Promise(r => setTimeout(r, 40 + Math.random() * 120));
                                await page.mouse.up().catch(() => {});
                                nextClickAt = Date.now() + 3000 + Math.random() * 4000;
                            }
                        }
                    }
                } catch (e) {
                    logMsg("[ts] klik widget: " + (e && e.message));
                }
            }

            await new Promise(r => setTimeout(r, interval));
            interval = Math.min(interval + 150, 2000);
        }
        throw new Error("timeout error");
    } finally {
        // puppeteer EventEmitter: nama method bisa `off` atau `removeListener` — coba keduanya
        try {
            if (typeof page.off === "function") page.off("request", onRequest);
            else if (typeof page.removeListener === "function") page.removeListener("request", onRequest);
        } catch (e) { logMsg("[ts] removeListener: " + (e && e.message)); }
        try { await page.setRequestInterception(false); } catch (e) { logMsg("[ts] disable interception: " + (e && e.message)); }
    }
}

async function executeTask(item) {
    let ctx = null;
    const signal = { aborted: false };
    try {
        ctx = await init_browser();
        running.set(item.id, { page: ctx.page, context: ctx.context, signal });
        const result = await turnstile(item.data, ctx.page, signal);
        send({ id: item.id, status: "ready", token: result.token });
    } catch (err) {
        send({ id: item.id, status: "error", err: err.message || String(err) });
    } finally {
        running.delete(item.id);
        if (ctx) {
            try { if (ctx.page) await ctx.page.close().catch(() => {}); } catch (e) { logMsg("[Task] close page: " + (e && e.message)); }
            try { if (ctx.context) await ctx.context.close().catch(() => {}); } catch (e) { logMsg("[Task] close context: " + (e && e.message)); }
            logMsg(`[Task ${item.id}] Context dibersihkan.`);
        }
        activeTasks--;
        tasksDone++;
        if (RECYCLE_EVERY_TASKS && tasksDone % RECYCLE_EVERY_TASKS === 0) pendingRecycle = true;
        if (pendingRecycle && activeTasks === 0 && browser) {
            pendingRecycle = false;
            logMsg(`[BROWSER] Recycle berkala tiap ${RECYCLE_EVERY_TASKS} task (total=${tasksDone}) — hemat RAM`);
            const b = browser;
            browser = null; browserAlive = false; browserGen++;
            try { await b.close(); } catch (e) { logMsg("[BROWSER] close: " + (e && e.message)); }
        } else if (activeTasks === 0) {
            scheduleIdleRecycle();
        }
        setImmediate(processQueue);
    }
}

function processQueue() {
    if (shuttingDown) return;
    clearTimeout(idleTimer);
    while (activeTasks < getMaxActive() && queue.length > 0) {
        const item = queue.shift();
        activeTasks++;
        executeTask(item); // .finally digantikan di dalam executeTask
    }
}

// Storage cleanup — hanya folder milik sendiri & lebih tua dari TMP_MAX_AGE_MS
setInterval(() => {
    try {
        const targets = ["/tmp", "/root/.cache"];
        let removed = 0;
        const now = Date.now();
        for (const dir of targets) {
            if (!fs.existsSync(dir)) continue;
            for (const entry of fs.readdirSync(dir)) {
                if (!(entry.startsWith("puppeteer_dev_") || entry.startsWith(".org.chromium.Chromium"))) continue;
                try {
                    const full = path.join(dir, entry);
                    const st = fs.statSync(full);
                    if (now - st.mtimeMs < TMP_MAX_AGE_MS) continue; // masih mungkin dipakai
                    fs.rmSync(full, { recursive: true, force: true });
                    removed++;
                } catch (e) {}
            }
        }
        if (removed > 0) logMsg(`[CLEANUP] ${removed} folder sisa dibersihkan.`);
    } catch (e) { logMsg("[CLEANUP] " + (e && e.message)); }
}, 300000).unref?.();

// stdin reader — NDJSON
const rl = readline.createInterface({ input: process.stdin });
rl.on("line", async (line) => {
    let msg;
    try { msg = JSON.parse(line); } catch { return; }

    // ---- cancel: dari queue ATAU yang sedang berjalan (force-close context) ----
    if (msg.cancel) {
        const id = String(msg.cancel).replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 64);
        const idx = queue.findIndex(x => x.id === id);
        if (idx >= 0) {
            queue.splice(idx, 1);
            logMsg(`[Task ${id}] Dihapus dari queue.`);
            return;
        }
        const entry = running.get(id);
        if (entry) {
            entry.signal.aborted = true;
            try { await entry.page.close({ runBeforeUnload: false }); } catch (e) {}
            try { await entry.context.close(); } catch (e) {}
            logMsg(`[Task ${id}] Dibatalkan paksa — context ditutup, RAM dibebaskan.`);
        }
        return;
    }

    const id = String(msg.id == null ? "" : msg.id).replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 64);
    if (!id || !msg.sitekey) {
        send({ id: id || "?", status: "error", err: "BAD_PARAMETERS" });
        return;
    }
    if (shuttingDown) {
        send({ id, status: "error", err: "SHUTTING_DOWN" });
        return;
    }
    if (queue.length >= getMaxQueue()) {
        send({ id, status: "error", err: "QUEUE_FULL" });
        return;
    }
    // ---- SSRF guard: URL valid, scheme http(s), bukan host internal/private ----
    const target = validateDomain(String(msg.domain || ""));
    if (!target) {
        send({ id, status: "error", err: "BAD_DOMAIN" });
        return;
    }
    queue.push({
        id,
        data: {
            domain: String(msg.domain),
            siteKey: String(msg.sitekey),
            action: msg.action == null ? null : String(msg.action),
            cdata: msg.cdata == null ? null : String(msg.cdata),
            pagedata: msg.pagedata == null ? null : String(msg.pagedata)
        }
    });
    processQueue();
});

// ---------- graceful shutdown: tolak task baru, tunggu yang berjalan, baru close ----------
let shutdownStarted = false;
async function shutdown(reason) {
    if (shutdownStarted) return;
    shutdownStarted = true;
    shuttingDown = true;
    logMsg(`[SHUTDOWN] ${reason} — menolak task baru, menunggu ${activeTasks} task aktif (maks 8s)...`);
    const deadline = Date.now() + 8000;
    while (activeTasks > 0 && Date.now() < deadline) {
        await new Promise(r => setTimeout(r, 100));
    }
    for (const entry of running.values()) {
        entry.signal.aborted = true;
        try { await entry.context.close(); } catch (e) {}
    }
    const b = browser;
    browser = null;
    browserAlive = false;
    browserGen++;
    if (b) { try { await b.close(); } catch (e) {} }
    process.exit(0);
}
rl.on("close", () => shutdown("stdin ditutup (parent exit?)")); // parent crash → child ikut mati, Chromium tidak yatim
process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));

send({ event: "ready" });
