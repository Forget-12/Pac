const { connect } = require("puppeteer-real-browser");
const fs = require("fs");
const BASE = "https://satoshifaucet.io";
const FAUCET = `${BASE}/faucet/currency/ltc`;
const PROXY = process.env.CF_PROXY || "";
function parseProxy(p){ try{ const u=new URL(p); return {host:u.hostname, port:u.port||"80", username:decodeURIComponent(u.username||""), password:decodeURIComponent(u.password||"")}; }catch(e){ return null; } }
const PX = parseProxy(PROXY);
const log = (m) => console.error(`[DS] ${m}`);
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
  page.on("requestfailed", (req) => { const f=req.failure(); if (f && f.errorText !== "net::ERR_ABORTED") log(`reqfail ${req.url().slice(0,70)} ${f.errorText}`); });
  await page.goto(FAUCET, { waitUntil: "domcontentloaded" }).catch(()=>{});
  await sleep(12000);
  await page.screenshot({ path: "cf-challenge.png", fullPage: false }).catch(()=>{});
  // dump frames tree
  const frames = page.frames();
  log("frames: " + frames.map(f=>f.url().slice(0,80)).join(" | "));
  for (const f of frames) {
    const src = f.url();
    log("frame url: " + src);
    if (src.includes("challenges.cloudflare.com")) {
      const box = await f.boundingBox().catch(() => null);
      log("cloudflare frame box: " + JSON.stringify(box));
      try { fs.writeFileSync("cf-frame.html", await f.content()); } catch (e) {}
    }
  }
  await Promise.race([browser.close(), sleep(2000)]).catch(()=>{});
  process.exit(0);
})();
