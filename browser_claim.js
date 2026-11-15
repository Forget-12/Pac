// browser_claim.js — daemon klaim via Chromium (proot+Xvfb), proxy + PAC.
// Tahap 1: buka homepage tanpa cookie -> CF clear (challenge platform DIRECT).
// Tahap 2: suntik cookie sesi proxy -> buka /faucet -> keluar form.
// Tahap 3: perintah stdin JSON-lines: challenge | submit | verify | page | quit
// Output stdout = JSON-lines respons. Log ke stderr.
const { connect } = require("puppeteer-real-browser");
const fs = require("fs");

const BASE = "https://satoshifaucet.io";
const FAUCET = `${BASE}/faucet/currency/ltc`;
const STATE = process.argv[2] || "sf-noproxy-state.json";
// profil persisten: browser nyata yang sama dipakai lagi (CF makin percaya setelah beberapa kunjungan)
const PROFILE = "/tmp/chrome-claim-" + Date.now();
const MAX_WAIT = parseInt(process.env.CF_WAIT || "270", 10) * 1000;
const PROXY = (process.env.CF_PROXY || "").trim();
const PAC = process.env.CF_PAC === "1";
function parseProxy(p) {
  if (!p) return null;
  try { const u = new URL(p); return { host: u.hostname, port: u.port || "80",
    username: decodeURIComponent(u.username || ""), password: decodeURIComponent(u.password || "") }; }
  catch (e) { return null; }
}
const log = (m) => console.error(`[BC] ${m}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PX = parseProxy(PROXY);

let browser, page;
const send = (obj) => process.stdout.write(JSON.stringify(obj) + "\n");

async function waitChallenge(stage) {
  const minWait = stage === "faucet" ? 30000 : 35000;   // tunggu CF redirect sendiri, jangan dipaksa
  const MAX = stage === "faucet" ? 300000 : 180000;
  const t0 = Date.now();
  let lastClick = 0;
  let clicks = 0;
  while (Date.now() - t0 < MAX) {
    const html = await page.content().catch(() => "");
    const low = html.toLowerCase();
    const challenge = low.includes("just a moment") || low.includes("performing security verification");
    const hasMarker = html.includes("csrf_token_name") || low.includes("auth/login")
      || low.includes("please wait") || low.includes("daily claims") || low.includes("dashboard");
    // CF selesai ketika: bukan halaman challenge DAN (url bersih atau ada penanda halaman)
    const url = page.url();
    const urlClean = url && !url.includes("__cf_chl_rt_tk");
    if (!challenge && urlClean && (hasMarker || html.length > 8000)) return true;
    const el = Date.now() - t0;
    // jangan coba apa-apa sebelum minWait — beri CF waktu redirect sendiri
    if (el >= minWait && Date.now() - lastClick > 5000 && clicks < 12) {
      lastClick = Date.now();
      try {
        const frames = await page.$$("iframe");
        for (const f of frames) {
          const src = await f.evaluate((el) => el.src).catch(() => "");
          if (!src.includes("challenges.cloudflare.com")) continue;
          const box = await f.boundingBox().catch(() => null);
          if (box && box.width > 0 && box.height > 0) {
            clicks++;
            const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
            log(`klik turnstile (${clicks}/12) di ${Math.round(cx)},${Math.round(cy)}`);
            await page.mouse.move(cx, cy, { steps: 7 }).catch(() => {});
            await page.mouse.down().catch(() => {});
            await sleep(90 + Math.random() * 150);
            await page.mouse.up().catch(() => {});
          }
        }
      } catch {}
    }
    if (el % 10000 < 1000) {
      const title = await page.title().catch(() => "");
      log(`menunggu CF... ${Math.round(el / 1000)}s title=${title.slice(0, 50)}`);
    }
    await sleep(1000);
  }
  return false;
}

async function setup() {
  const ctx = await connect({
    headless: false, turnstile: true,
    proxy: (!PAC && PX) ? { host: PX.host, port: PX.port, username: PX.username, password: PX.password } : {},
    customConfig: { chromePath: "/usr/bin/chromium",
      args: ["--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--window-size=1366,768",
        "--lang=en-US,en","--no-first-run","--no-default-browser-check","--user-data-dir=" + PROFILE,
        "--disable-http2","--disable-quic"].concat(PAC ? ["--proxy-pac-url=file://" + __dirname + "/gw.pac"] : []) },
  });
  browser = ctx.browser;
  page = ctx.page || (await browser.newPage());
  page.setDefaultNavigationTimeout(90000); page.setDefaultTimeout(90000);
  if (PX && PX.username) await page.authenticate({ username: PX.username, password: PX.password }).catch(() => {});
  page.on("requestfailed", (req) => { const f = req.failure(); log(`reqfail ${req.url().slice(0, 90)} ${f ? f.errorText : ""}`); });
  page.on("response", (res) => { if (res.status() >= 400) log(`HTTP ${res.status()} ${res.url().slice(0, 100)}`); });

  // 1) homepage tanpa cookie -> CF clear
  log("buka homepage (tanpa cookie)...");
  await page.goto(BASE + "/", { waitUntil: "domcontentloaded" }).catch(() => {});
  const clear1 = await waitChallenge("home");
  log(`homepage cf-clear=${clear1} url=${page.url()}`);

  // 2) suntik cookie sesi
  let state = {};
  try { state = JSON.parse(fs.readFileSync(STATE, "utf8")); } catch {}
  const cookies = Object.entries(state.cookies || {})
    .filter(([k]) => k !== "__ua__" && k !== "cf_clearance")
    .map(([name, value]) => ({ name, value, domain: "satoshifaucet.io", path: "/" }));
  // juga bawa cf_clearance hasil tahap 1 jika ada
  const cksNow = await page.cookies(BASE).catch(() => []);
  const clearance = cksNow.find((c) => c.name === "cf_clearance");
  if (clearance) cookies.push({ name: "cf_clearance", value: clearance.value, domain: "satoshifaucet.io", path: "/" });
  if (cookies.length) {
    await page.setCookie(...cookies).catch((e) => log("setCookie: " + e.message));
    log(`${cookies.length} cookie sesi disuntik`);
  }

  // 3) ke /faucet
  await page.goto(FAUCET, { waitUntil: "domcontentloaded" }).catch(() => {});
  const clear2 = await waitChallenge("faucet");
  log(`faucet cf-clear=${clear2} url=${page.url()}`);
  const html = await page.content().catch(() => "");
  const fields = await page.evaluate(() => {
    const get = (n) => { const el = document.querySelector(`[name="${n}"]`); return el ? el.value : ""; };
    return {
      csrf: get("csrf_token_name"), token: get("token"), nonce: get("claim_nonce"),
      wallet: get("wallet"), captcha: get("captcha"),
      title: document.title, url: location.href,
      bodyText: document.body ? document.body.innerText.slice(0, 3000) : "",
    };
  }).catch((e) => ({ error: String(e.message || e) }));
  send({ ready: true, cf_clear: clear1 && clear2, fields, htmlLen: html.length });
}

async function fetchChallenge() {
  const r = await page.evaluate(async () => {
    const resp = await fetch('/cosmos/challenge/faucet_ltc?_=' + Date.now(), {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'include',
    });
    return { status: resp.status, text: await resp.text() };
  }).catch((e) => ({ error: String(e.message || e) }));
  if (r.text) {
    try { send({ ok: true, challenge: JSON.parse(r.text) }); }
    catch { send({ ok: false, err: "challenge bukan JSON", body: String(r.text).slice(0, 200) }); }
  } else {
    send({ ok: false, err: r.error || ("HTTP?") });
  }
}

async function postForm(url, data) {
  const r = await page.evaluate(async (u, d) => {
    const body = new URLSearchParams(d).toString();
    const resp = await fetch(u, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Requested-With': 'XMLHttpRequest' },
      body,
    });
    return { status: resp.status, text: await resp.text() };
  }, url, data).catch((e) => ({ error: String(e.message || e) }));
  return r;
}

// ---- stdin JSON-lines loop ----
const rl = require("readline").createInterface({ input: process.stdin });
rl.on("line", async (line) => {
  let cmd = null;
  try { cmd = JSON.parse(line); } catch {}
  if (!cmd || !cmd.cmd) { send({ ok: false, err: "bad cmd" }); return; }
  try {
    if (cmd.cmd === "init") { /* setup already ran */ send({ ok: true }); return; }
    if (cmd.cmd === "challenge") { await fetchChallenge(); return; }
    if (cmd.cmd === "check") {
      const r = await postForm("/cosmos/check/faucet_ltc", {
        csrf_token_name: cmd.csrf, token: cmd.token, hp: "", pts: cmd.pts,
      });
      let j = null; try { j = JSON.parse(r.text || "null"); } catch {}
      send({ ok: !!j, http: r.status, json: j, raw: j ? undefined : String(r.text || "").slice(0, 200) });
      return;
    }
    if (cmd.cmd === "verify") {
      const r = await postForm("/faucet/verify/ltc", {
        csrf_token_name: cmd.csrf, token: cmd.token, claim_nonce: cmd.nonce,
        uf: cmd.uf, utt: cmd.utt, ls: cmd.ls, captcha: "sf_cosmos",
        sfz_pass: cmd.pass, sfz_hp: "", wallet: cmd.wallet,
      });
      const html2 = await page.content().catch(() => "");
      send({ ok: true, http: r.status, text: String(r.text || "").slice(0, 4000),
             daily: (html2.match(/Daily\s*Claims[\s\S]{0,240}?(\d+)\s*\/\s*(\d+)/i) || []).slice(1, 3) });
      return;
    }
    if (cmd.cmd === "page") {
      await page.goto(FAUCET, { waitUntil: "domcontentloaded" }).catch(() => {});
      await waitChallenge("faucet");
      const html3 = await page.content().catch(() => "");
      const daily = (html3.match(/Daily\s*Claims[\s\S]{0,240}?(\d+)\s*\/\s*(\d+)/i) || []).slice(1, 3);
      send({ ok: true, daily, htmlLen: html3.length, url: page.url() });
      return;
    }
    if (cmd.cmd === "anchor") { send({ ok: true, url: page.url() }); return; }
    if (cmd.cmd === "quit") {
      send({ ok: true });
      process.exit(0);
    }
    send({ ok: false, err: "unknown cmd" });
  } catch (e) {
    send({ ok: false, err: String(e.message || e) });
  }
});

(async () => {
  try { await setup(); }
  catch (e) { log("ERROR " + (e.message || e)); send({ ready: false, err: String(e.message || e) }); process.exit(1); }
})();
