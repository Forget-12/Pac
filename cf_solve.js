// cf_solve.js — ambil cf_clearance untuk satoshifaucet.io via Chromium (proot Ubuntu + Xvfb)
// Output: cf-clearance.json  { ok, cf_clearance, ua, cookies, ts }
// Pakai: xvfb-run -a node cf_solve.js sf-noproxy-state.json cf-clearance.json
const { connect } = require("puppeteer-real-browser");
const fs = require("fs");

const BASE = "https://satoshifaucet.io";
const FAUCET = `${BASE}/faucet/currency/ltc`;
const STATE = process.argv[2] || "sf-noproxy-state.json";
const OUT = process.argv[3] || "cf-clearance.json";
const MAX_WAIT = parseInt(process.env.CF_WAIT || "150", 10) * 1000;
const PROXY = (process.env.CF_PROXY || process.argv[4] || "").trim();

function parseProxy(p) {
  if (!p) return null;
  try {
    const u = new URL(p);
    const host = u.hostname;
    const port = u.port || (u.protocol === "https:" ? "443" : "80");
    return {
      host,
      port,
      server: `http://${host}:${port}`,
      username: decodeURIComponent(u.username || ""),
      password: decodeURIComponent(u.password || ""),
    };
  } catch (e) {
    log("proxy tidak valid: " + (e.message || e));
    return null;
  }
}
const log = (m) => console.error(`[CF] ${m}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PX = parseProxy(PROXY);
(async () => {
  let state = {};
  try { state = JSON.parse(fs.readFileSync(STATE, "utf8")); } catch {}
  const raw = (state.cookies || {});
  const cookies = Object.entries(raw)
    .filter(([k]) => k !== "__ua__" && k !== "cf_clearance")
    .map(([name, value]) => ({ name, value, domain: "satoshifaucet.io", path: "/" }));

  let browser;
  try {
    const ctx = await connect({
      headless: false,
      turnstile: true,
      proxy: PX ? {
        host: PX.host,
        port: PX.port,
        username: PX.username,
        password: PX.password,
      } : {},
      customConfig: {
        chromePath: "/usr/bin/chromium",
        args: [
          "--no-sandbox",
          "--disable-dev-shm-usage",
          "--disable-gpu",
          "--window-size=1280,900",
          "--lang=en-US,en",
          "--no-first-run",
          "--no-default-browser-check",
        ],
      },
    });
    browser = ctx.browser;
    const page = ctx.page || (await browser.newPage());
    page.setDefaultNavigationTimeout(90000);
    page.setDefaultTimeout(90000);
    if (PX) {
      log(`pakai proxy ${PX.server}${PX.username ? " (auth)" : ""}`);
      if (PX.username) {
        await page.authenticate({ username: PX.username, password: PX.password })
          .catch((e) => log("proxy auth: " + e.message));
      }
    }
    page.on("requestfailed", (req) => {
      const f = req.failure();
      log(`reqfail ${req.url().slice(0, 90)} ${f ? f.errorText : ""}`);
    });
    page.on("console", (msg) => {
      if (msg.type() === "error") log(`console: ${msg.text().slice(0, 140)}`);
    });
    page.on("response", (res) => {
      if (res.status() >= 400) {
        log(`HTTP ${res.status()} ${res.url().slice(0, 120)}`);
      }
    });

    log("buka homepage...");
    await page.goto(BASE + "/", { waitUntil: "domcontentloaded" }).catch(() => {});
    if (cookies.length) {
      await page.setCookie(...cookies).catch((e) => log("setCookie: " + e.message));
      log(`${cookies.length} cookie sesi disuntik`);
    }

    log("buka /faucet/currency/ltc ...");
    await page.goto(FAUCET, { waitUntil: "domcontentloaded" }).catch(() => {});

    const t0 = Date.now();
    let ok = false;
    let lastClick = 0;
    while (Date.now() - t0 < MAX_WAIT) {
      const html = await page.content().catch(() => "");
      const low = html.slice(0, 5000).toLowerCase();
      const cksNow = await page.cookies(BASE).catch(() => []);
      const hasClearance = cksNow.some((c) => c.name === "cf_clearance" && c.value);
      const challenge = low.includes("just a moment")
        || low.includes("performing security verification");
      if ((html.includes("csrf_token_name") && !challenge)
          || (hasClearance && !challenge)) {
        ok = true;
        break;
      }
      // klik widget turnstile bila ada
      if (Date.now() - lastClick > 4000) {
        lastClick = Date.now();
        try {
          const frames = await page.$$("iframe");
          for (const f of frames) {
            const src = await f.evaluate((el) => el.src).catch(() => "");
            if (!src.includes("challenges.cloudflare.com")) continue;
            const box = await f.boundingBox().catch(() => null);
            if (box && box.width > 0 && box.height > 0) {
              await page.mouse.move(box.x + 30, box.y + box.height / 2, { steps: 5 }).catch(() => {});
              await page.mouse.down().catch(() => {});
              await sleep(80 + Math.random() * 120);
              await page.mouse.up().catch(() => {});
            }
          }
        } catch {}
      }
      const el = Math.round((Date.now() - t0) / 1000);
      if (el % 10 === 0) {
        const title = await page.title().catch(() => "");
        log(`menunggu CF... ${el}s url=${page.url()} title=${title.slice(0, 60)}`);
        if (el === 20 || el === 50) {
          await page.screenshot({ path: "cf-debug.png", fullPage: false })
            .catch(() => {});
        }
      }
      await sleep(1000);
    }

    const cks = await page.cookies(BASE).catch(() => []);
    const map = {};
    for (const c of cks) map[c.name] = c.value;
    const ua = await page.evaluate(() => navigator.userAgent).catch(() => "");
    const out = {
      ok,
      cf_clearance: map["cf_clearance"] || "",
      ua,
      cookies: map,
      ts: new Date().toISOString(),
    };
    fs.writeFileSync(OUT, JSON.stringify(out, null, 1));
    log(ok ? `SUKSES cf_clearance=${(map["cf_clearance"] || "").slice(0, 24)}...`
           : "GAGAL (masih challenge)");
    process.exitCode = ok ? 0 : 3;
  } catch (e) {
    log("ERROR: " + (e.message || e));
    try {
      fs.writeFileSync(OUT, JSON.stringify({ ok: false, error: String(e.message || e), ts: new Date().toISOString() }, null, 1));
    } catch {}
    process.exitCode = 1;
  } finally {
    try { if (browser) await browser.close(); } catch {}
  }
})();