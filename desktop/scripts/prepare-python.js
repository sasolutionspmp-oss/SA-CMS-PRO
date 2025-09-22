#!/usr/bin/env node
const { spawnSync } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const projectRoot = path.resolve(__dirname, "..");
const runtimeDir = path.join(projectRoot, "python-runtime");
const requirementsPath = path.resolve(projectRoot, "..", "requirements.txt");

if (!fs.existsSync(requirementsPath)) {
  console.error("Unable to locate requirements.txt at", requirementsPath);
  process.exit(1);
}

const pythonCommand =
  process.env.SA_CMS_PYTHON || (process.platform === "win32" ? "python" : "python3");

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: "inherit",
    ...options,
  });

  if (result.error) {
    throw result.error;
  }

  if (result.status !== 0) {
    throw new Error(`Command failed: ${command} ${args.join(" ")}`);
  }
}

function ensureVenv() {
  const marker = path.join(runtimeDir, "pyvenv.cfg");

  if (fs.existsSync(marker)) {
    return;
  }

  if (fs.existsSync(runtimeDir)) {
    fs.rmSync(runtimeDir, { recursive: true, force: true });
  }

  console.log("Creating bundled Python runtime at", runtimeDir);
  run(pythonCommand, ["-m", "venv", runtimeDir]);
}

function getPipPath() {
  if (process.platform === "win32") {
    return path.join(runtimeDir, "Scripts", "pip.exe");
  }
  return path.join(runtimeDir, "bin", "pip");
}

function installRequirements() {
  const requirementHash = crypto
    .createHash("sha256")
    .update(fs.readFileSync(requirementsPath))
    .digest("hex");
  const markerFile = path.join(runtimeDir, ".requirements-hash");

  let installedHash = null;
  if (fs.existsSync(markerFile)) {
    installedHash = fs.readFileSync(markerFile, "utf8");
  }

  const pip = getPipPath();

  if (installedHash === requirementHash) {
    console.log("Python runtime already up to date. Skipping dependency install.");
    return;
  }

  console.log("Installing backend dependencies into bundled runtime...");
  run(pip, ["install", "--upgrade", "pip"]);
  run(pip, ["install", "-r", requirementsPath]);

  fs.writeFileSync(markerFile, requirementHash);
}

try {
  ensureVenv();
  installRequirements();
  console.log("Bundled Python runtime ready.");
} catch (err) {
  console.error(err.message || err);
  process.exit(1);
}
