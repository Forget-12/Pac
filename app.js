const express = require("express");
const { execFile, spawn } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const os = require("os");

const app = express();
const port = process.env.PORT || 3000;
app.use(express.json({ limit: "50mb" }));

// Gunakan /app/cfsolve (sesuai Dockerfile baru)
const CFSOLVE_BIN = process.env.CFSOLVE_BIN || "/app/cfsolve"; 
const TASK_TIMEOUT = parseInt(process.env.TASK_TIMEOUT, 10) || 120000;
const TASKS_FILE = path.join(os.tmpdir(), "tasks.json");
const PROFILES_DIR = "/app/profiles";

const PYTHON_BIN = process.env.PYTHON_BIN || "python3";
const ADSLAB_RUNNER = path.join(__dirname, "adslab_runner.py");
const WAF_RUNNER = path.join(__dirname, "cf_waf_solver.py");

const MAX_ACTIVE = 2; 
const MAX_QUEUE = 8;   

let activeTasks = 0;
const queue = [];

let PROFILES = [];
try {
    const dirs = fs.readdirSync(PROFILES_DIR, { withFileTypes: true })
        .filter(dirent => dirent.isDirectory()).map(dirent => dirent.name);
    for (const dir of dirs) {
        const mainJsonPath = path.join(PROFILES_DIR, dir, "main.json");
        if (fs.existsSync(mainJsonPath)) PROFILES.push(mainJsonPath);
    }
} catch (e) { console.error("Gagal baca profil:", e.message); }
if (PROFILES.length === 0) PROFILES.push("/app/profiles/iphone-13/main.json"); 

let profileIndex = 0;
function getNextProfile() {
    const prof = PROFILES[profileIndex];
    profileIndex = (profileIndex + 1) % PROFILES.length;
    return prof;
}

let tasks = {};
if (fs.existsSync(TASKS_FILE)) {
    try { tasks = JSON.parse(fs.readFileSync(TASKS_FILE, "utf8")); } catch (e) {}
}
function saveTasks() { try { fs.writeFileSync(TASKS_FILE, JSON.stringify(tasks, null, 2)); } catch (e) {} }

function runCfsolve(pageUrl, { proxy, sitekey, action, cdata, blankPage, mode, profilePath, ua } = {}) {
    return new Promise((resolve, reject) => {
        const workDir = fs.mkdtempSync(path.join(os.tmpdir(), "cfsolve-"));
        const args = ["--page", pageUrl, workDir, "--solve", "--fingerprint", profilePath];
        
        if (proxy) args.push("--proxy", proxy);
        if (mode === "turnstile" && sitekey) {
            args.push("--sitekey", sitekey);
            if (blankPage) args.push("--blank-page");
            if (action) args.push("--action", action);
            if (cdata) args.push("--cdata", cdata);
        }
        
        execFile(CFSOLVE_BIN, args, { timeout: TASK_TIMEOUT }, (err, stdout, stderr) => {
            try { fs.rmSync(workDir, { recursive: true, force: true }); } catch {}
            if (err) return reject(new Error((stderr || err.message || "").toString().trim().split('\n').pop()));
            const out = (stdout || "").trim();
            if (out.startsWith("cf_clearance=")) return resolve({ cf_clearance: out.split("=")[1] });
            return resolve({ token: out });
        });
    });
}

function runAdslab({ sitekey, siteurl, subId, proxy, cookies, ua } = {}) {
    return new Promise((resolve, reject) => {
        const child = spawn(PYTHON_BIN, [ADSLAB_RUNNER], {
            cwd: __dirname, env: { ...process.env, PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" },
            stdio: ["pipe", "pipe", "pipe"]
        });
        let stdout = "", stderr = "", settled = false;
        let timer = setTimeout(() => { if(!settled) child.kill("SIGKILL"); }, TASK_TIMEOUT);
        const finish = (handler, value) => { if (settled) return; settled = true; clearTimeout(timer); handler(value); };

        child.stdout.on("data", c => { stdout += c.toString(); console.log(`[Py] ${c.toString().trim()}`); });
        child.stderr.on("data", c => { stderr += c.toString(); console.error(`[Py-Err] ${c.toString().trim()}`); });
        child.on("error", err => finish(reject, err));
        child.on("close", () => {
            try {
                const parsed = JSON.parse(stdout.trim().split("\n").pop());
                if (parsed.ok) finish(resolve, { token: parsed.token });
                else finish(reject, new Error(parsed.error || "AdsLab failed"));
            } catch (e) { finish(reject, new Error(stderr.trim().split("\n").pop() || "Invalid JSON AdsLab")); }
        });
        child.stdin.end(JSON.stringify({ task: { websiteKey: sitekey, websiteURL: siteurl, subId: subId, proxy: proxy, cookies: cookies, ua: ua } }));
    });
}

function runCfWaf({ siteurl, proxy, cookies, ua } = {}) {
    return new Promise((resolve, reject) => {
        const child = spawn(PYTHON_BIN, [WAF_RUNNER], {
            cwd: __dirname, env: { ...process.env, PYTHONUNBUFFERED: "1", PYTHONIOENCODING: "utf-8" },
            stdio: ["pipe", "pipe", "pipe"]
        });
        let stdout = "", stderr = "", settled = false;
        let timer = setTimeout(() => { if(!settled) child.kill("SIGKILL"); }, TASK_TIMEOUT);
        const finish = (handler, value) => { if (settled) return; settled = true; clearTimeout(timer); handler(value); };

        child.stdout.on("data", c => { stdout += c.toString(); });
        child.stderr.on("data", c => { stderr += c.toString(); console.error(`[WAF-Py-Err] ${c.toString().trim()}`); });
        child.on("error", err => finish(reject, err));
        child.on("close", () => {
            try {
                const lines = stdout.trim().split("\n");
                const lastLine = lines[lines.length - 1];
                const parsed = JSON.parse(lastLine);
                if (parsed.ok) finish(resolve, { cf_clearance: parsed.token, ua: parsed.ua, type: parsed.type });
                else finish(reject, new Error(parsed.error || "CF WAF failed"));
            } catch (e) { 
                finish(reject, new Error(`Python Error: ${stderr || stdout}`)); 
            }
        });
        child.stdin.end(JSON.stringify({ task: { websiteURL: siteurl, proxy: proxy, cookies: cookies, ua: ua } }));
    });
}

function processQueue() {
    while (activeTasks < MAX_ACTIVE && queue.length > 0) {
        const taskJob = queue.shift();
        activeTasks++;
        taskJob.run().finally(() => { activeTasks--; setImmediate(processQueue); });
    }
}

function processQueue() {
    while (activeTasks < MAX_ACTIVE && queue.length > 0) {
        const taskJob = queue.shift();
        activeTasks++;
        taskJob.run().finally(() => { activeTasks--; setImmediate(processQueue); });
    }
}

const solveHandler = async (req, res) => {
    const body = req.body || {};
    if (body.taskId && tasks[body.taskId]) return res.json(tasks[body.taskId]);
    if (!body.task) return res.status(400).json({ error: "Missing task" });

    const task = body.task;
    const type = String(task.type || "").toLowerCase();
    const isAdslab = type.includes("ads") || type.includes("alcaptcha");
    const isWaf = type === "cfwaf" || type === "waf" || type.includes("interstitial");
    // Proxy HANYA dari payload task — env tidak lagi menimpa (membersihkan alur python)
    const proxy = String(task.proxy || "").trim();
    const cookies = task.cookies || "";
    const ua = task.ua || task.userAgent || "";  // NEW: accept UA from task or session

    if (queue.length >= MAX_QUEUE) return res.status(429).json({ status: "error", err: { usr: "QUEUE_FULL" } });

    const taskId = crypto.randomUUID().replace(/-/g, "").slice(0, 12);
    const selectedProfile = (isAdslab || isWaf) ? null : getNextProfile();
    const profileName = selectedProfile ? path.basename(path.dirname(selectedProfile)) : type;

    tasks[taskId] = { status: "pending", taskId };
    saveTasks();
    
    res.json({ taskId, status: "pending" });
    console.log(`[TASK] ${taskId} masuk antrean. Tipe: ${profileName}`);

    const taskJob = {
        run: async () => {
            try {
                let solution;
                if (isAdslab) {
                    solution = await runAdslab({
                        sitekey: task.websiteKey || task.sitekey,
                        siteurl: task.websiteURL || task.siteurl,
                        subId: task.subId || task.subid || "widget_user",
                        proxy: proxy, cookies: cookies, ua: ua
                    });
                } else if (isWaf) {
                    solution = await runCfWaf({
                        siteurl: task.websiteURL || task.siteurl,
                        proxy: proxy, cookies: cookies, ua: ua
                    });
                } else {
                    const result = await runCfsolve(task.websiteURL || task.websiteUrl, {
                        proxy, sitekey: task.websiteKey, action: task.action,
                        cdata: task.cdata, blankPage: task.blankPage, mode: type, profilePath: selectedProfile, ua: ua
                    });
                    solution = type === "turnstile" ? { token: result.token } : { cf_clearance: result.cf_clearance };
                }
                tasks[taskId] = { status: "ready", taskId, solution };
                console.log(`[SUKSES] Task ${taskId} selesai (${type})`);
            } catch (err) {
                tasks[taskId] = { status: "error", taskId, err: { usr: "ERROR_CAPTCHA_UNSOLVABLE", api: err.message } };
                console.log(`[GAGAL] Task ${taskId} (${type}): ${err.message}`);
            } finally {
                saveTasks();
                setTimeout(() => { delete tasks[taskId]; saveTasks(); }, 60000);
            }
        }
    };

    queue.push(taskJob);
    processQueue();
};

app.post("/solve", solveHandler);
app.post("/solve/adslab", solveHandler);

app.listen(port, "0.0.0.0", () => {
    console.log(`🚀 Server berjalan di port ${port}`);
    console.log(`Profil terdeteksi: ${PROFILES.length}`);
});
