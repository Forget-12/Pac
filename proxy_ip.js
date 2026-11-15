const { connect } = require("puppeteer-real-browser");
const u = new URL(process.env.CF_PROXY);
(async () => {
  const ctx = await connect({
    headless: false,
    proxy: { host: u.hostname, port: u.port || "80", username: decodeURIComponent(u.username), password: decodeURIComponent(u.password) },
    customConfig: { chromePath: "/usr/bin/chromium", args: ["--no-sandbox","--disable-dev-shm-usage","--disable-gpu"] },
  });
  const page = ctx.page || await ctx.browser.newPage();
  await page.goto("https://api.ipify.org?format=json", { waitUntil: "domcontentloaded", timeout: 60000 });
  console.log(await page.evaluate(() => document.body.innerText));
  await ctx.browser.close();
})();
