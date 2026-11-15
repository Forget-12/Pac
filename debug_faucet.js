const { connect } = require("puppeteer-real-browser");
const fs = require("fs");
const BASE = "https://satoshifaucet.io";
const FAUCET = `${BASE}/faucet/currency/ltc`;
const PROXY = process.env.CF_PROXY || "";
function parseProxy(p){ try{ const u=new URL(p); return {host:u.hostname, port:u.port||"80", username:decodeURIComponent(u.username||""), password:decodeURIComponent(u.password||"")}; }catch(e){ return null; } }
const PX = parseProxy(PROXY);
const log = (m) => console.error(`[DF] ${m}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const ctx = await connect({
    headless: false, turnstile: true,
    proxy: PX ? { host: PX.host, port: PX.port, username: PX.username, password: PX.password } : {},
    customConfig: { chromePath: "/usr/bin/chromium",
      args: ["--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--window-size=1366,768","--lang=en-US,en","--no-first-run","--no-default-browser-check","--user-data-dir=/tmp/chrome-claim-profile","--proxy-pac-url=file://" + __dirname + "/gw.pac"] },
  });
  const browser = ctx.browser;
  const page = ctx.page || (await browser.newPage());
  page.setDefaultNavigationTimeout(90000); page.setDefaultTimeout(90000);
  if (PX && PX.username) await page.authenticate({ username: PX.username, password: PX.password }).catch(()=>{});
  page.on("requestfailed", (req) => { const f=req.failure(); if (f && f.errorText !== "net::ERR_ABORTED") log(`reqfail ${req.url().slice(0,80)} ${f.errorText}`); });
  page.on("response", (res) => { if (res.status() >= 400) log(`HTTP ${res.status()} ${res.url().slice(0,90)}`); });
  log("goto faucet (no cookies injected)");
  await page.goto(FAUCET, { waitUntil: "domcontentloaded" }).catch(() => {});
  const t0 = Date.now();
  while (Date.now() - t0 < 120000) {
    const title = await page.title().catch(() => "");
    const html = await page.content().catch(() => "");
    const cks = await page.cookies(BASE).catch(() => []);
    const hasClearance = cks.some((c) => c.name === "cf_clearance");
    const el = Math.round((Date.now() - t0) / 1000);
    if (el % 10 === 0) log(`wait ${el}s title=${title.slice(0,40)} html=${html.length} clearance=${hasClearance}`);
    const low = html.toLowerCase();
    const challenge = low.includes("just a moment") || low.includes("performing security verification");
    if (!challenge) {
      log(`done title=${title} clearance=${hasClearance} html=${html.length}`);
      fs.writeFileSync("faucet-direct.html", html);
      break;
    }
    await sleep(1000);
  }
  const cks = await page.cookies(BASE).catch(() => []);
  log("cookies: " + cks.map((c) => c.name).join(","));
  await Promise.race([browser.close(), sleep(2000)]).catch(() => {});
  process.exit(0);
})();
