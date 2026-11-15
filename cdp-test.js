const puppeteer = require("puppeteer-core");

(async () => {
    let browser;

    try {
        browser = await puppeteer.connect({
            browserURL: "http://127.0.0.1:9222",
            defaultViewport: null
        });

        console.log("BERHASIL: Node terhubung ke Chromium");

        const pages = await browser.pages();
        console.log("Jumlah tab:", pages.length);

        const page = await browser.newPage();
        await page.goto("https://example.com", {
            waitUntil: "domcontentloaded",
            timeout: 30000
        });

        console.log("Judul halaman:", await page.title());

    } catch (error) {
        console.error("CDP ERROR:", error.message);
    } finally {
        if (browser) {
            browser.disconnect();
        }
    }
})();

