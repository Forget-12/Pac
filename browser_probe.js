// browser_probe.js — buka /faucet via Chromium (proot+Xvfb), selesaikan CF,
// lalu ambil form fields + challenge JSON. Output: browser-probe.json
const { connect } = require("puppeteer-real-browser");
const fs = require("fs");

const BASE = "https://satoshifaucet.io";
const FAUCET = `${BASE}/faucet/currency/ltc`;
const STATE = process.argv[2] || "sf-noproxy-state.json";
const OUT = process.argv[3] || "browser-probe.json";
const MAX_WAIT = parseInt(process.env.CF_WAIT || "150", 10) * 1000;
const PROXY = (process.env.CF_PROXY || "").trim();

function parseProxy(p) {
  if (!p) return null;
  try {
    const u = new URL(p);
    const host = u.hostname;
    const port = u.port || (u.protocol === "https:" ? "443" : "80");
    return {
      host, port, server: `http://${host}:${port}`,
      username: decodeURIComponent(u.username || ""),
      password: decodeURIComponent(u.password || ""),
    };
  } catch (e) { log("proxy tidak valid: " + (e.message || e)); return null; }
}
const log = (m) => console.error(`[BP] ${m}`);
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
      proxy: PX ? { host: PX.host, port: PX.port, username: PX.username, password: PX.password } : {},
      customConfig: {
        chromePath: "/usr/bin/chromium",
        args: ["--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--window-size=1280,900","--lang=en-US,en","--no-first-run","--no-default-browser-check","--proxy-bypass-list=challenges.cloudflare.com"],
      },
    });
    browser = ctx.browser;
    const page = ctx.page || (await browser.newPage());
    page.setDefaultNavigationTimeout(90000);
    page.setDefaultTimeout(90000);
    if (PX) {
      log(`pakai proxy ${PX.server}${PX.username ? " (auth)" : ""}`);
      if (PX.username) await page.authenticate({ username: PX.username, password: PX.password }).catch((e) => log("proxy auth: " + e.message));
    }
    page.on("requestfailed", (req) => {
      const f = req.failure();
      log(`reqfail ${req.url().slice(0, 90)} ${f ? f.errorText : ""}`);
    });
    page.on("console", (msg) => { if (msg.type() === "error") log(`console: ${msg.text().slice(0, 140)}`); });
    page.on("response", (res) => { if (res.status() >= 400) log(`HTTP ${res.status()} ${res.url().slice(0, 120)}`); });

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
    while (Date.now() - t0 < MAX_WAIT) {
      const html = await page.content().catch(() => "");
      const low = html.toLowerCase();
      const challenge = low.includes("just a moment")
        || low.includes("performing security verification")
        || low.includes("_cf_chl_opt");
      if (html.includes("csrf_token_name") && !challenge) { ok = true; break; }
      const el = Math.round((Date.now() - t0) / 1000);
      if (el % 10 === 0) log(`menunggu CF... ${el}s url=${page.url()} title=${(await page.title().catch(() => "")).slice(0, 60)}`);
      await sleep(1000);
    }
    log("CF ok=" + ok + " url=" + page.url());
    const html = await page.content().catch(() => "");
    fs.writeFileSync("faucet-page.html", html);

    const fields = await page.evaluate(() => {
      const get = (n) => { const el = document.querySelector(`[name="${n}"]`); return el ? el.value : ""; };
      return {
        csrf: get("csrf_token_name"), token: get("token"), nonce: get("claim_nonce"),
        wallet: get("wallet"), captcha: get("captcha"),
        title: document.title,
        url: location.href,
        bodyText: document.body ? document.body.innerText.slice(0, 2000) : "",
      };
    }).catch((e) => ({ error: String(e.message || e) }));
    log("fields: " + JSON.stringify(fields).slice(0, 400));

    let challenge = null;
    try {
      challenge = await page.evaluate(async () => {
        const r = await fetch('/cosmos/challenge/faucet_ltc?_=' + Date.now(), {
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
          credentials: 'include',
        });
        const t = await r.text();
        return { status: r.status, text: t };
      });
    } catch (e) { challenge = { error: String(e.message || e) }; }
    if (challenge && challenge.text) {
      try {
        const j = JSON.parse(challenge.text);
        if (j.img) fs.writeFileSync("browser-challenge.b64", j.img);
        log("challenge keys: " + Object.keys(j).join(",") + " imgLen=" + (j.img ? j.img.length : 0));
        challenge = { status: challenge.status, json: j, text: undefined };
      } catch (e) { log("challenge bukan JSON: " + challenge.text.slice(0, 160)); }
    }

    const cks = await page.cookies(BASE).catch(() => []);
    const map = {};
    for (const c of cks) map[c.name] = c.value;
    const ua = await page.evaluate(() => navigator.userAgent).catch(() => "");
    const out = {
      ok, url: page.url(), ua, cookies: map, fields, challenge,
      htmlLen: html.length, ts: new Date().toISOString(),
    };
    fs.writeFileSync(OUT, JSON.stringify(out, null, 1));
    log("OUT " + OUT + " ok=" + ok + " htmlLen=" + html.length);
    process.exitCode = ok ? 0 : 3;
  } catch (e) {
    log("ERROR: " + (e.message || e));
    try { fs.writeFileSync(OUT, JSON.stringify({ ok: false, error: String(e.message || e), ts: new Date().toISOString() }, null, 1)); } catch {}
    process.exitCode = 1;
  } finally {
    try { if (browser) await browser.close(); } catch {}
  }
})();
