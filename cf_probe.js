// cf_probe.js — cek apakah proxy bisa menyelesaikan CF di /faucet tanpa cookie sesi.
// Pakai: CF_PROXY=... node cf_probe.js out.json
const { connect } = require("puppeteer-real-browser");
const fs = require("fs");
const BASE = "https://satoshifaucet.io";
const FAUCET = `${BASE}/faucet/currency/ltc`;
const OUT = process.argv[2] || "cf-probe.json";
const MAX_WAIT = parseInt(process.env.CF_WAIT || "120", 10) * 1000;
const PROXY = (process.env.CF_PROXY || "").trim();
const PAC = process.env.CF_PAC === "1";
function parseProxy(p) {
  if (!p) return null;
  try {
    const u = new URL(p);
    return { host: u.hostname, port: u.port || "80",
      username: decodeURIComponent(u.username || ""),
      password: decodeURIComponent(u.password || "") };
  } catch (e) { return null; }
}
const log = (m) => console.error(`[CP] ${m}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PX = parseProxy(PROXY);
(async () => {
  let browser;
  try {
    const ctx = await connect({
      headless: false, turnstile: true,
      proxy: (!PAC && PX) ? { host: PX.host, port: PX.port, username: PX.username, password: PX.password } : {},
      customConfig: { chromePath: "/usr/bin/chromium",
        args: ["--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--window-size=1366,768","--lang=en-US,en","--no-first-run","--no-default-browser-check","--user-data-dir=/tmp/chrome-cf-profile","--disable-http2","--disable-quic"]
          .concat(PAC ? ["--proxy-pac-url=file://" + __dirname + "/gw.pac"] : []) },
    });
    browser = ctx.browser;
    const page = ctx.page || (await browser.newPage());
    page.setDefaultNavigationTimeout(90000); page.setDefaultTimeout(90000);
    if (PX && PX.username) await page.authenticate({ username: PX.username, password: PX.password }).catch(() => {});
    page.on("requestfailed", (req) => { const f = req.failure(); log(`reqfail ${req.url().slice(0, 90)} ${f ? f.errorText : ""}`); });
    page.on("response", (res) => { if (res.status() >= 400) log(`HTTP ${res.status()} ${res.url().slice(0, 100)}`); });
    log("goto " + FAUCET);
    await page.goto(FAUCET, { waitUntil: "domcontentloaded" }).catch(() => {});
    const t0 = Date.now();
    let ok = false;
    let lastClick = 0;
    while (Date.now() - t0 < MAX_WAIT) {
      const html = await page.content().catch(() => "");
      const low = html.toLowerCase();
      const challenge = low.includes("just a moment") || low.includes("performing security verification") || low.includes("_cf_chl_opt");
      const done = html.includes("csrf_token_name") || low.includes("auth/login")
        || low.includes("please wait") || low.includes("daily claims")
        || (low.includes("dashboard") && !challenge);
      if (done && !challenge) { ok = true; break; }
      // klik checkbox Turnstile bila ada
      if (Date.now() - lastClick > 4000) {
        lastClick = Date.now();
        try {
          const frames = await page.$$("iframe");
          for (const f of frames) {
            const src = await f.evaluate((el) => el.src).catch(() => "");
            if (!src.includes("challenges.cloudflare.com")) continue;
            const box = await f.boundingBox().catch(() => null);
            if (box && box.width > 0 && box.height > 0) {
              log(`klik turnstile ${Math.round(box.x)},${Math.round(box.y)} ${Math.round(box.width)}x${Math.round(box.height)}`);
              await page.mouse.move(box.x + 30, box.y + box.height / 2, { steps: 5 }).catch(() => {});
              await page.mouse.down().catch(() => {});
              await sleep(80 + Math.random() * 120);
              await page.mouse.up().catch(() => {});
            }
          }
        } catch {}
      }
      const el = Math.round((Date.now() - t0) / 1000);
      if (el % 10 === 0) log(`wait ${el}s title=${(await page.title().catch(() => "")).slice(0, 50)}`);
      await sleep(1000);
    }
    const html = await page.content().catch(() => "");
    const cks = await page.cookies(BASE).catch(() => []);
    const map = {}; for (const c of cks) map[c.name] = c.value;
    const body = await page.evaluate(() => document.body ? document.body.innerText.slice(0, 500) : "").catch(() => "");
    const out = { ok, url: page.url(), title: await page.title().catch(() => ""),
      has_csrf: html.includes("csrf_token_name"), has_login: /form[^>]*auth\/login/i.test(html),
      clearance: !!map.cf_clearance, cookies: map, body: body.slice(0, 500), ts: new Date().toISOString() };
    fs.writeFileSync(OUT, JSON.stringify(out, null, 1));
    log(`OUT ok=${ok} title=${out.title.slice(0, 40)} csrf=${out.has_csrf} login=${out.has_login} clearance=${out.clearance}`);
    process.exitCode = ok ? 0 : 3;
  } catch (e) {
    log("ERROR " + (e.message || e));
    try { fs.writeFileSync(OUT, JSON.stringify({ ok: false, error: String(e.message || e) }, null, 1)); } catch {}
    process.exitCode = 1;
  } finally { try { if (browser) await browser.close(); } catch {} }
})();
