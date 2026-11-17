const { connect } = require("puppeteer-real-browser");

async function solveHard(url, proxy, ua) {
    console.log("[HardCF] Memulai browser...");
    let browser = null;
    try {
        const args = ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'];
        if (ua) args.push('--user-agent=' + ua);
        const conn = await connect({
            headless: true,
            turnstile: true,
            customConfig: {
                chromePath: process.env.PUPPETEER_EXECUTABLE_PATH || "/usr/bin/chromium",
                args: args
            }
        });
        browser = conn.browser;
        const page = await browser.newPage();

        if (proxy) {
            const auth = proxy.split('@')[0].split('//')[1].split(':');
            await page.authenticate({ username: auth[0], password: auth[1] });
        }

        if (ua) await page.setUserAgent(ua);
        await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 });
        await new Promise(r => setTimeout(r, 8000)); 
        
        const cookies = await page.cookies();
        const cfCookie = cookies.find(c => c.name === 'cf_clearance');
        const uaResult = await page.evaluate(() => navigator.userAgent);
        
        await browser.close();
        return cfCookie ? { ok: true, token: cfCookie.value, ua: uaResult } : { ok: false, error: "No cf_clearance" };
    } catch (err) {
        if (browser) await browser.close();
        return { ok: false, error: err.message };
    }
}

process.stdin.on('data', async (data) => {
    try {
        const { url, proxy, ua } = JSON.parse(data.toString());
        const res = await solveHard(url, proxy, ua);
        console.log(JSON.stringify(res));
    } catch (e) {
        console.log(JSON.stringify({ ok: false, error: e.message }));
    }
    process.exit(0);
});
