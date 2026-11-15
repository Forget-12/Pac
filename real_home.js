const { connect } = require("puppeteer-real-browser");
const fs = require("fs");
const PROXY = process.env.CF_PROXY || "";
const PAC = process.env.CF_PAC === "1";
function parseProxy(p){ try{ const u=new URL(p); return {host:u.hostname, port:u.port||80, username:decodeURIComponent(u.username||u.user||""), password:decodeURIComponent(u.password||"")}; }catch(e){ return null; } }
const PX = parseProxy(PROXY);
const log = (m) => console.error(`[RH] ${m}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const ctx = await connect({
    headless: false, turnstile: true,
    proxy: PX ? { host: PX.host, port: PX.port, username: PX.username, password: PX.password } : {},
    customConfig: { chromePath: "/usr/bin/chromium",
      args: ["--no-sandbox","--disable-dev-shm-usage","--window-size=1366,768","--lang=en-US,en","--no-first-run","--no-default-browser-check","--proxy-pac-url=file://" + __dirname + "/gw.pac"] },
  });
  const browser = ctx.browser;
  const page = ctx.page || (await browser.newPage());
  page.setDefaultNavigationTimeout(60000);
  page.setDefaultTimeout(60000);
  page.on("requestfailed", (req) => {
    const f = req.failure();
    const u = req.url();
    if (/bmcdn|adsboosters|cleverwebserver|clvrads|ccnsad|clever-core|telegram\.im/i.test(u))
      log(`adfail ${u.slice(0,80)} ${f ? f.errorText : ""}`);
  });
  page.on("response", (res) => {
    const u = res.url(); const s = res.status();
    if (/bmcdn|adsboosters|cleverwebserver|clvrads|ccnsad|telegram\.im/i.test(u) && s >= 400)
      log(`adhttp ${s} ${u.slice(0,80)}`);
  });
  log("goto homepage");
  await page.goto("https://satoshifaucet.io/", { waitUntil: "domcontentloaded" }).catch(()=>{});
  log("wait 15s for ads/js...");
  await sleep(15000);
  const html = await page.content().catch(()=>"");
  log("htmlLen=" + html.length);
  fs.writeFileSync("homepage-real.html", html);
  const hasAdsBlocker = /Ads Blocker Detected|Adblock/i.test(html);
  log("Ads Blocker dialog in page: " + hasAdsBlocker);
  // count iframe ad hosts
  const iframes = await page.$$eval("iframe", els => els.map(e => e.src).slice(0, 30)).catch(()=>[]);
  log("iframes: " + JSON.stringify(iframes));
  await page.screenshot({ path: "homepage-real.png" }).catch(()=>{});
  await Promise.race([browser.close(), sleep(2000)]).catch(()=>{});
  process.exit(0);
})();
