const { connect } = require("puppeteer-real-browser");
const fs = require("fs");
const BASE = "https://satoshifaucet.io";
const FAUCET = `${BASE}/faucet/currency/ltc`;
const log = (m) => console.error(`[DP2] ${m}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const ctx = await connect({
    headless: false, turnstile: true,
    proxy: {},
    customConfig: { chromePath: "/usr/bin/chromium",
      args: ["--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--window-size=1366,768","--lang=en-US,en","--no-first-run","--no-default-browser-check","--user-data-dir=/tmp/chrome-claim-profile"] },
  });
  const browser = ctx.browser;
  const page = ctx.page || (await browser.newPage());
  page.setDefaultNavigationTimeout(90000); page.setDefaultTimeout(90000);
  let state = {}; try { state = JSON.parse(fs.readFileSync("sf-noproxy-state.json","utf8")); } catch {}
  const cookies = Object.entries(state.cookies||{}).filter(([k])=>k!=="__ua__"&&k!=="cf_clearance").map(([name,value])=>({name,value,domain:"satoshifaucet.io",path:"/"}));
  if (cookies.length) { await page.setCookie(...cookies).catch(e=>log("setCookie: "+e)); log(cookies.length+" cookie sesi disuntik"); }
  await page.goto(FAUCET, { waitUntil: "domcontentloaded" }).catch(()=>{});
  await sleep(20000);
  const title = await page.title().catch(()=>"");
  const url = page.url();
  const cks = await page.cookies(BASE).catch(()=>[]);
  const cf_clearance = cks.find(c=>c.name==="cf_clearance");
  log("title="+title+" url="+url);
  log("cookies: "+cks.map(c=>c.name).join(","));
  log("cf_clearance len="+(cf_clearance?cf_clearance.value.length:0));
  await page.screenshot({ path: "faucet-state.png" }).catch(()=>{});
  await Promise.race([browser.close(), sleep(2000)]).catch(()=>{});
  process.exit(0);
})();
