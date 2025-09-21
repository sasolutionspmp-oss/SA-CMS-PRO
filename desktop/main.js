const { app, BrowserWindow } = require("electron");
const path = require("path");
const { spawn } = require("child_process");
const http = require("http");

let mainWindow = null;
let backendProcess = null;
let isQuitting = false;

const isDev = process.env.NODE_ENV === "development" || !app.isPackaged;
const devServerUrl = process.env.VITE_DEV_SERVER_URL || "http://localhost:5173";
const backendDir = path.resolve(__dirname, "../backend");
const pythonCommand = process.env.SA_CMS_PYTHON || (process.platform === "win32" ? "python" : "python3");

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function pingBackend() {
  return new Promise((resolve) => {
    const req = http.request(
      {
        host: "127.0.0.1",
        port: 8000,
        path: "/healthz",
        timeout: 1000,
      },
      (res) => {
        res.resume();
        resolve(res.statusCode === 200);
      },
    );
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
    req.end();
  });
}

async function bootstrapDatabase() {
  const result = spawn(pythonCommand, ["scripts/dev.py"], {
    cwd: backendDir,
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
    stdio: "inherit",
  });

  return new Promise((resolve, reject) => {
    result.on("exit", (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`Database bootstrap failed with exit code ${code}`));
      }
    });
    result.on("error", reject);
  });
}

function startBackend() {
  if (backendProcess) {
    return;
  }

  backendProcess = spawn(
    pythonCommand,
    ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
    {
      cwd: backendDir,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
      stdio: "inherit",
    },
  );

  backendProcess.on("exit", (code) => {
    backendProcess = null;
    if (!isQuitting && code !== 0) {
      console.error(`Backend process exited unexpectedly with code ${code}`);
    }
  });

  backendProcess.on("error", (err) => {
    console.error("Failed to start backend:", err);
  });
}

async function ensureBackend() {
  if (await pingBackend()) {
    return;
  }
  try {
    await bootstrapDatabase();
  } catch (err) {
    console.error(err);
  }
  startBackend();
  for (let i = 0; i < 10; i += 1) {
    if (await pingBackend()) {
      return;
    }
    await wait(500);
  }
  console.warn("Backend did not respond in time. Continuing startup.");
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
    },
  });

  if (isDev) {
    mainWindow.loadURL(devServerUrl);
    mainWindow.webContents.openDevTools({ mode: "detach" });
  } else {
    const indexHtml = path.resolve(__dirname, "../frontend/dist/index.html");
    mainWindow.loadFile(indexHtml);
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.whenReady().then(async () => {
  await ensureBackend();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("before-quit", () => {
  isQuitting = true;
  if (backendProcess) {
    backendProcess.kill();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
