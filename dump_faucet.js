const { connect } = require("puppeteer-real-browser");
const fs = require("fs");
const BASE = "https://satoshifaucet.io";
const FAUCET = `${BASE}/faucet/currency/ltc`;
const PROXY = "";
const PAC = false;
function parseProxy(p){ try{ const u=new URL(p); return {host:u.hostname, port:u.port||null, username:decodeURIComponent(u.username||u.user||""), password:decodeURIComponent(u.password||"")}; }catch(e){ return null; } }
const PX = parseProxy(PROXY);
const log = (m) => console.error(`[DP] ${m}`);
(async () => {
  const ctx = await connect({
    headless: false, turnstile: true,
    proxy: (!PAC && PX) ? { host: PX.host, port: PX.port, username: PX.username, password: PX.password } : {},
    customConfig: { chromePath: "/usr/bin/chromium",
      args: ["--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--window-size=1366,768","--lang=en-US,en","--no-first-run","--no-default-browser-check","--user-data-dir=/tmp/chrome-dump-profile"]
        .concat(PAC ? ["--proxy-pac-url=file://" + __dirname + "/gw.pac"] : []) },
  });
  const browser = ctx.browser;
  const page = ctx.page || (await browser.newPage());
  page.setDefaultNavigationTimeout(60000); page.setDefaultTimeout(60000);
  if (PX && PX.username) await page.authenticate({ username: PX.username, password: PX.password }).catch(()=>{});
  let state = {}; try { state = JSON.parse(fs.readFileSync("sf-noproxy-state.json","utf8")); } catch {}
  const cookies = Object.entries(state.cookies||{}).filter(([k])=>k!=="__ua__"&&k!=="cf_clearance").map(([name,value])=>({name,value,domain:"satoshifaucet.io",path:"/"}));
  if (cookies.length) { await page.setCookie(...cookies).catch(e=>log("setCookie: "+e)); log(cookies.length+" cookie sesi disuntik"); }
  await page.goto(FAUCET, { waitUntil: "networkidle0" }).catch(()=>{});
  await new Promise(r=>setTimeout(r,12000));
  const html = await page.content().catch(()=>"");
  const title = await page.title().catch(()=>"");
  fs.writeFileSync("faucet-dump-direct.html", html);
  log("title="+title+" htmlLen="+html.length+" url="+page.url());
  await Promise.race([browser.close(), new Promise(r=>setTimeout(r,3000))]).catch(()=>{});
  process.exit(0);
})();
