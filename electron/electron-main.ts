import { app, BrowserWindow, Tray, Menu } from 'electron';
import * as path from 'path';
import * as childProcess from 'child_process';
import getPort from 'get-port';

let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let backendProcess: childProcess.ChildProcess | null = null;

async function createWindow() {
  const port = await getPort();
  const backendPath = path.join(__dirname, '..', 'backend', 'main.py');
  backendProcess = childProcess.spawn('uvicorn', [`${backendPath.replace(/\\/g, '/')}:app`, '--port', String(port)], {
    stdio: 'inherit',
  });

  const healthUrl = `http://127.0.0.1:${port}/health`;
  await waitForHealth(healthUrl);

  mainWindow = new BrowserWindow({
    width: 1024,
    height: 768,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  mainWindow.loadURL(`file://${path.join(__dirname, '..', 'build', 'index.html')}`);

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  tray = new Tray(path.join(__dirname, 'icon.png'));
  const contextMenu = Menu.buildFromTemplate([
    { label: 'Show', click: () => mainWindow?.show() },
    { label: 'Quit', click: () => app.quit() },
  ]);
  tray.setToolTip('SA-CMS-Pro');
  tray.setContextMenu(contextMenu);
}

function waitForHealth(url: string, retries = 30, interval = 500): Promise<void> {
  const fetch = require('node-fetch');
  return new Promise((resolve, reject) => {
    const attempt = () => {
      fetch(url)
        .then((res: any) => (res.ok ? resolve() : retry()))
        .catch(retry);
    };
    const retry = () => {
      if (--retries <= 0) return reject(new Error('Backend failed to start'));
      setTimeout(attempt, interval);
    };
    attempt();
  });
}

app.on('ready', createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  if (backendProcess) {
    backendProcess.kill();
  }
});
