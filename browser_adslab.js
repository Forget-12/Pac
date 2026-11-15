// browser_adslab.js — solve AdsLab captcha via real Chromium (proot Ubuntu + Xvfb)
// Protocol JSON-lines:
//   1) Print {"ok":true,"img":"/tmp/adslab-<ts>.png"} after screenshot
//   2) Read one line from stdin = OCR digits from parent (e.g., Python+tesseract)
//   3) Fill iframe input with digits, submit, wait for ALCAPTCHA_SOLVED
//   4) Print {"ok":true,"token":"<uuid>"} and exit
// Usage: xvfb-run -a --server-args='-screen 0 1280x1024x24' node browser_adslab.js <pageurl> <timeout_ms>

const { connect } = require("puppeteer-real-browser");
const fs = require("fs");
const path = require("path");

const PAGEURL = process.argv[2] || "https://satoshifaucet.io/";
const TIMEOUT_MS = parseInt(process.argv[3] || "180000", 10);

const log = (m) => console.error(`[ADSLAB] ${m}`);
const send = (obj) => process.stdout.write(JSON.stringify(obj) + "\n");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ----- inject adslab widget source -----
const WIDGET_JS = fs.readFileSync(path.join(__dirname, "adslab-widget.js"), "utf8");

async function main() {
  let browser, page;
  try {
    log(`start page=${PAGEURL} timeout=${TIMEOUT_MS}ms`);
    const ctx = await connect({
      headless: false,
      turnstile: true,
      customConfig: {
        chromePath: "/usr/bin/chromium",
        args: [
          "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
          "--window-size=1366,768", "--lang=en-US,en", "--no-first-run",
          "--no-default-browser-check", "--disable-http2", "--disable-quic",
        ],
      },
    });
    browser = ctx.browser;
    page = ctx.page || (await browser.newPage());
    page.setDefaultNavigationTimeout(90000);
    page.setDefaultTimeout(90000);

    await page.goto(PAGEURL, { waitUntil: "domcontentloaded" }).catch(() => {});
    await sleep(2000);

    // 1) inject widget JS
    await page.evaluate(WIDGET_JS);
    log("widget injected");

    // 2) wait for .adslab-captcha container with data-sitekey
    await page.waitForSelector(".adslab-captcha[data-sitekey]", { timeout: 30000 });
    log("found adslab-captcha container");

    // 3) find fingerprint button (startUi) inside container
    // structure: .alcaptcha-container > .alcaptcha-start-ui (holds fingerprint)
    const startBtn = await page.$(".adslab-captcha .alcaptcha-start-ui");
    if (!startBtn) throw new Error("alcaptcha-start-ui not found");

    const box = await startBtn.boundingBox();
    if (!box || box.width === 0 || box.height === 0) {
      throw new Error("start button box zero");
    }
    const cx = box.x + box.width / 2;
    const cy = box.y + box.height / 2;
    log(`click fingerprint at ${Math.round(cx)},${Math.round(cy)}`);

    // 4) hold mousedown 1100ms (HOLD_TIME=1000ms in widget + margin)
    await page.mouse.move(cx, cy, { steps: 7 });
    await page.mouse.down();
    await sleep(1100);
    await page.mouse.up();
    log("fingerprint hold done");

    // 5) wait for iframe to show (class al-show)
    await page.waitForFunction(() => {
      const iframe = document.querySelector(".adslab-captcha iframe.alcaptcha-iframe.al-show");
      return !!iframe;
    }, { timeout: 30000 });
    log("iframe visible");

    // 6) find the iframe frame (cross-origin adslab.me)
    const frames = page.frames();
    let adslabFrame = null;
    for (const f of frames) {
      const url = f.url();
      if (url.includes("adslab.me/alcaptcha")) {
        adslabFrame = f;
        break;
      }
    }
    if (!adslabFrame) {
      // fallback: wait a bit and re-scan
      await sleep(2000);
      const frames2 = page.frames();
      for (const f of frames2) {
        if (f.url().includes("adslab.me/alcaptcha")) { adslabFrame = f; break; }
      }
    }
    if (!adslabFrame) throw new Error("adslab iframe frame not found");
    log("adslab frame acquired");

    // 7) wait for captcha image inside iframe
    // typical: <img src="blob:..." or data: or direct image>
    await adslabFrame.waitForSelector("img", { timeout: 30000 });
    const imgEl = await adslabFrame.$("img");
    if (!imgEl) throw new Error("no img in iframe");

    // 8) screenshot image
    const ts = Date.now();
    const imgPath = `/tmp/adslab-${ts}.png`;
    await imgEl.screenshot({ path: imgPath });
    log(`screenshot saved ${imgPath}`);

    // 9) signal parent with image path
    send({ ok: true, img: imgPath });

    // 10) read OCR digits from stdin (one line)
    const digits = await new Promise((resolve, reject) => {
      const to = setTimeout(() => reject(new Error("stdin timeout")), TIMEOUT_MS - 20000);
      const rl = require("readline").createInterface({ input: process.stdin });
      rl.on("line", (line) => {
        clearTimeout(to);
        rl.close();
        resolve(line.trim());
      });
    });
    log(`OCR digits received: ${digits}`);

    // 11) fill input in iframe and submit
    // find input[type="text"] or input without type (number field)
    const input = await adslabFrame.$('input[type="text"], input:not([type="hidden"])');
    if (!input) throw new Error("no input in iframe");
    await input.type(digits, { delay: 50 });
    log("digits typed");

    // find submit button (button[type="submit"] or button with text Submit/Verify)
    const submitBtn = await adslabFrame.$('button[type="submit"], button:not([type])');
    if (submitBtn) {
      await submitBtn.click();
      log("submit clicked");
    } else {
      // press Enter
      await adslabFrame.keyboard.press("Enter");
      log("Enter pressed");
    }

    // 12) wait for token in main page (hidden input[name="alcaptcha-response"])
    const token = await page.waitForFunction(() => {
      const el = document.querySelector('input[name="alcaptcha-response"]');
      return el ? el.value : null;
    }, { timeout: TIMEOUT_MS - 5000 }).catch(() => null);
    if (!token) throw new Error("token not found after submit");

    send({ ok: true, token });
    log("token received");
  } catch (e) {
    log(`ERROR: ${e.message || e}`);
    send({ ok: false, err: String(e.message || e) });
    process.exitCode = 1;
  } finally {
    if (browser) {
      try { await browser.close(); } catch {}
    }
  }
}

main();