const { connect } = require("puppeteer-real-browser");
const fs = require("fs");
const https = require("https");

const KEY = "90d4b91a1c3c2e430fa3e17f62a4d545";
const EMAIL = process.env.SF_EMAIL || "gi2h370@gmail.com";
const PROXY = process.env.CF_PROXY || "";
const PAC = process.env.CF_PAC === "1";
function parseProxy(p){ try{ const u=new URL(p); return {host:u.hostname, port:u.port||80, username:decodeURIComponent(u.username||u.user||""), password:decodeURIComponent(u.password||"")}; }catch(e){ return null; } }
const PX = parseProxy(PROXY);
const log = (m) => console.error(`[RF] ${m}`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function httpsReq(opts, bodyData) {
  return new Promise((resolve, reject) => {
    const req = https.request(opts, (res) => {
      let body = "";
      res.on("data", (d) => body += d);
      res.on("end", () => resolve({ status: res.statusCode, body: body.trim() }));
    });
    req.on("error", reject);
    if (bodyData) req.write(bodyData);
    req.end();
  });
}

async function solveAdsLab() {
  const sitekey = "lA0LtcfCXUxnBWifcQrqRsmPi6sSV3HtrpyRodRg";
  const pageurl = "https://satoshifaucet.io/";
  const form = new URLSearchParams({ key: KEY, method: "adslab", sitekey, pageurl, domain: "satoshifaucet.io" }).toString();
  const h = await httpsReq({ method: "POST", host: "api.tertuyul.my.id", path: "/in.php", headers: {
    "Content-Type": "application/x-www-form-urlencoded", "Content-Length": Buffer.byteLength(form) } }, form);
  const id = h.body;
  if (id.startsWith("ERROR_")) throw new Error("adslab submit: " + id);
  log(`adslab task id=${id}`);
  for (let i = 0; i < 40; i++) {
    await sleep(3000);
    const r = await httpsReq({ host: "api.tertuyul.my.id", path: `/res.php?key=${KEY}&action=get&id=${id}` });
    if (r.body === "CAPCHA_NOT_READY") continue;
    if (r.body.startsWith("ERROR_")) throw new Error("adslab poll: " + r.body);
    return r.body;
  }
  throw new Error("adslab timeout");
}

(async () => {
  const ctx = await connect({
    headless: false, turnstile: true,
    proxy: PX ? { host: PX.host, port: PX.port, username: PX.username, password: PX.password } : {},
    customConfig: { chromePath: "/usr/bin/chromium",
      args: ["--no-sandbox","--disable-dev-shm-usage","--window-size=1366,768","--lang=en-US,en","--no-first-run","--no-default-browser-check","--user-data-dir=/tmp/chrome-full-claim-profile","--proxy-pac-url=file://" + __dirname + "/gw.pac"] },
  });
  const browser = ctx.browser;
  const page = ctx.page || (await browser.newPage());
  page.setDefaultNavigationTimeout(90000); page.setDefaultTimeout(90000);
  if (PX && PX.username) await page.authenticate({ username: PX.username, password: PX.password }).catch(()=>{});
  page.on("requestfailed", (req) => {
    const f = req.failure(); const u = req.url();
    if (/bmcdn|adsboosters|cleverwebserver|clvrads|ccnsad/i.test(u)) log(`adfail ${u.slice(0,80)} ${f?f.errorText:""}`);
    else if (f && f.errorText !== "net::ERR_ABORTED") log(`reqfail ${u.slice(0,80)} ${f?f.errorText:""}`);
  });

  log("goto homepage");
  await page.goto("https://satoshifaucet.io/", { waitUntil: "domcontentloaded" });
  log("wait for ads/js...");
  await sleep(12000);

  // isi email
  const email = process.env.SF_EMAIL || EMAIL;
  await page.waitForSelector("#InputEmail", { timeout: 30000 });
  await page.focus("#InputEmail");
  await page.type("#InputEmail", email, { delay: 25 });
  const emailFilled = await page.$eval("#InputEmail", (el) => el.value).catch(() => "?");
  log("email filled: " + emailFilled);

  // baca hidden fields
  const fields = await page.evaluate(() => {
    const get = (n) => { const el = document.querySelector(`[name="${n}"]`); return el ? el.value : null; };
    return { csrf: get("csrf_token_name"), uf: get("uf"), utt: get("utt"), ls: get("ls"), captcha: get("captcha") };
  });
  log("fields: " + JSON.stringify(fields));

  // solve alcaptcha
  log("solving AdsLab via Tertuyul...");
  const tok = await solveAdsLab().catch(e => { log("adslab ERR: " + e); return null; });
  if (!tok) { log("AdsLab gagal — berhenti"); await Promise.race([browser.close(), sleep(1000)]).catch(()=>{}); process.exit(3); }
  log(`adslab token len=${tok.length} prefix=${tok.slice(0,24)}`);
  await page.evaluate((t) => {
    const el = document.querySelector('input[name="alcaptcha-response"], #alcaptcha-response, [name="alcaptcha-response"]');
    if (el) { el.value = t; el.dispatchEvent(new Event("input", { bubbles: true })); return true; }
    // fallback: buat hidden input
    const h = document.createElement("input"); h.type = "hidden"; h.name = "alcaptcha-response"; h.value = t; document.body.appendChild(h);
    return false;
  }, tok).then((had) => log("alcaptcha-response field had=" + had));

  // submit form (klik tombol Login Now)
  log("click Login Now");
  await page.click(".hero_form_btn").catch(e => log("click err: " + e));
  await sleep(12000);
  const url1 = page.url();
  const title1 = await page.title().catch(() => "");
  log(`after login: url=${url1} title=${title1}`);
  const html1 = await page.content().catch(() => "");
  log(`htmlLen=${html1.length} loginForm still=${/form[^>]*auth\/login/i.test(html1)}`);

  // klik "Faucet LTC" dari menu (hulu menu)
  const ltc = await page.$('a[href*="/faucet/currency/ltc"]');
  if (ltc) { log("click Faucet LTC menu..."); await ltc.click(); await sleep(15000); }
  log(`faucet url=${page.url()} title=${await page.title().catch(()=> "")}`);
  const html2 = await page.content().catch(() => "");
  fs.writeFileSync("claim-faucet.html", html2);
  log(`faucet htmlLen=${html2.length} csrf=${html2.includes("csrf_token_name")}`);
  // juga lihat yang terlihat
  await page.screenshot({ path: "claim-full.png", fullPage: false });

  await Promise.race([browser.close(), sleep(3000)]).catch(() => {});
  process.exit(0);
})();
