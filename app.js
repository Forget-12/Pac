/**
 * app.js — Universal Captcha Solver API (Railway)
 */
const express = require("express");
const crypto = require("crypto");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const app = express();
app.use(express.json({ limit: "50mb" }));

const PORT = process.env.PORT || 3000;
const MAX_ACTIVE = parseInt(process.env.MAX_ACTIVE, 10) || 2;
const MAX_QUEUE = parseInt(process.env.MAX_QUEUE, 10) || 10;
const TASK_TIMEOUT = parseInt(process.env.TASK_TIMEOUT, 10) || 120000;
const CLEANUP_INTERVAL = 60000;

const queue = [];
const activeTasks = new Set();
const results = new Map();

function processQueue() {
    if (activeTasks.size >= MAX_ACTIVE || queue.length === 0) return;
    const task = queue.shift();
    activeTasks.add(task.id);

    const timeoutTimer = setTimeout(() => {
        if (activeTasks.has(task.id)) {
            activeTasks.delete(task.id);
            results.set(task.id, { status: "error", err: { usr: "ERROR_TIMEOUT", api: "Task timeout exceeded" }, timestamp: Date.now() });
            processQueue();
        }
    }, TASK_TIMEOUT);

    const cleanup = (status, solution = null, err = null) => {
        clearTimeout(timeoutTimer);
        if (!activeTasks.has(task.id)) return;
        activeTasks.delete(task.id);
        results.set(task.id, { status, solution, err, timestamp: Date.now() });
        processQueue();
    };

    if (task.type === "AdsLabTask") runAdslab(task.data, cleanup);
    else runTurnstile(task.data, cleanup);
}

function runAdslab(data, callback) {
    console.log(`[AdsLab] Memulai task...`);
    const py = spawn("python3", ["adslab_runner.py"], { cwd: __dirname, stdio: ["pipe", "pipe", "pipe"] });
    let stdoutData = "", stderrData = "";
    py.stdout.on("data", (c) => stdoutData += c.toString());
    py.stderr.on("data", (c) => stderrData += c.toString());
    py.on("close", (code) => {
        if (code !== 0 || !stdoutData.trim()) return callback("error", null, { usr: "ERROR_CAPTCHA_UNSOLVABLE", api: stderrData });
        try {
            const parsed = JSON.parse(stdoutData.trim().split("\n").pop());
            if (parsed.ok && parsed.token) callback("ready", { token: parsed.token });
            else callback("error", null, { usr: "ERROR_CAPTCHA_UNSOLVABLE", api: parsed.error });
        } catch (e) {
            callback("error", null, { usr: "ERROR_PARSE", api: "Invalid JSON" });
        }
    });
    py.stdin.write(JSON.stringify({ task: data }) + "\n");
    py.stdin.end();
}

function runTurnstile(data, callback) {
    console.log(`[Turnstile] Memulai task...`);
    const binPath = path.join(__dirname, "cfsolve");
    if (!fs.existsSync(binPath)) return callback("error", null, { usr: "ERROR_SETUP", api: "cfsolve not found" });
    const args = [data.websiteURL, data.websiteKey || ""];
    if (data.proxy) args.push("--proxy", data.proxy);
    const child = spawn(binPath, args, { cwd: __dirname });
    let stdoutData = "", stderrData = "";
    child.stdout.on("data", (c) => stdoutData += c.toString());
    child.stderr.on("data", (c) => stderrData += c.toString());
    child.on("close", (code) => {
        if (code !== 0) return callback("error", null, { usr: "ERROR_CAPTCHA_UNSOLVABLE", api: stderrData });
        const output = stdoutData.trim();
        try {
            const parsed = JSON.parse(output);
            if (parsed.token) return callback("ready", { token: parsed.token });
        } catch (e) {
            if (output.length > 50) return callback("ready", { token: output });
        }
        callback("error", null, { usr: "ERROR_CAPTCHA_UNSOLVABLE", api: output });
    });
}

app.get("/", (req, res) => res.json({ status: "ok" }));

app.post("/solve", (req, res) => {
    const body = req.body;
    if (body.taskId) {
        const result = results.get(body.taskId);
        if (!result) return res.json({ status: "pending", taskId: body.taskId });
        return res.json({ status: result.status, taskId: body.taskId, solution: result.solution, err: result.err });
    }
    if (!body.task || !body.task.websiteURL) return res.status(400).json({ status: "error", err: "BAD_REQUEST" });
    if (queue.length >= MAX_QUEUE) return res.status(429).json({ status: "error", err: "QUEUE_FULL" });

    const taskId = crypto.randomBytes(6).toString("hex");
    results.set(taskId, { status: "pending", timestamp: Date.now() });
    queue.push({ id: taskId, type: body.task.type || "turnstile", data: body.task });
    res.json({ taskId, status: "pending" });
    processQueue();
});

setInterval(() => {
    const now = Date.now();
    for (const [id, data] of results.entries()) if (now - data.timestamp > 300000) results.delete(id);
}, CLEANUP_INTERVAL);

app.listen(PORT, () => console.log(`🚀 Server on port ${PORT}`));
