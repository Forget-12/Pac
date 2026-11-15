const { connect } = require("puppeteer-real-browser");
const fs = require("fs");
const BASE = "https://satoshifaucet.io";
const FAUCET = `${BASE}/faucet/currency/ltc`;
const PROXY = process.env.CF_PROXY || "";
function parseProxy(p){ try{ const u=new URL(p); return {host:u.hostname, port:u.port||80, username:decodeURIComponent(u.username||u.user||""), password:decodeURIComponent(u.password||"")}; }catch(e){ return null; } }
const PX = parseProxy(PROXY);
const log = (m) => console.error(`[TP] ${m}`);
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
  page.on("requestfailed", (req) => {
    const f = req.failure();
    const url = req.url();
    if (/bmcdn|adsboosters|cleverweb|clvrads|ccnsad/i.test(url))
      log(`adfail ${url.slice(0,80)} ${f ? f.errorText : ""}`);
    else if (f && f.errorText !== "net::ERR_ABORTED")
      log(`reqfail ${url.slice(0,80)} ${f.errorText}`);
  });
  page.on("console", (msg) => { if (msg.type() === "error") log(`console: ${msg.text().slice(0,140)}`); });
  let state = {}; try { state = JSON.parse(fs.readFileSync("sf-noproxy-state.json","utf8")); } catch {}
  const cookies = Object.entries(state.cookies||{}).filter(([k])=>k!=="__ua__"&&k!=="cf_clearance").map(([name,value])=>({name,value,domain:"satoshifaucet.io",path:"/"}));
  if (cookies.length) { await page.setCookie(...cookies).catch(e=>log("setCookie: "+e)); log(cookies.length+" cookie sesi disuntik"); }
  await page.goto(FAUCET, { waitUntil: "domcontentloaded" }).catch(()=>{});
  const t0 = Date.now();
  while (Date.now() - t0 < 120000) {
    const html = await page.content().catch(()=>"");
    const title = await page.title().catch(()=>"");
    const url = page.url();
    const low = html.toLowerCase();
    const clear = low.includes("csrf_token_name") && !low.includes("just a moment");
    if (clear) {
      log(`SUCCESS title=${title} htmlLen=${html.length} url=${url}`);
      fs.writeFileSync("faucet-pac-success.html", html);
      break;
    }
    const el = Math.round((Date.now() - t0) / 1000);
    if (el % 10 === 0) log(`wait ${el}s title=${title.slice(0,50)} html=${html.length}`);
    await sleep(1000);
  }
  const cks = await page.cookies(BASE).catch(()=>[]);
  log("cookies: "+cks.map(c=>c.name).join(","));
  await Promise.race([browser.close(), sleep(2000)]).catch(()=>{});
  process.exit(0);
})();
