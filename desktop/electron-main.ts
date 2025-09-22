import { app, BrowserWindow } from 'electron'
import path from 'path'
import fs from 'fs'
import { spawn, ChildProcess } from 'child_process'

const BACKEND_HOST = '127.0.0.1'
const BACKEND_PORT = 8000

let backend: ChildProcess | undefined

function getRuntimeDirectory(): string {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'python-runtime')
  }

  return path.join(app.getAppPath(), 'python-runtime')
}

function getPythonExecutable(): string {
  const runtimeDir = getRuntimeDirectory()
  if (fs.existsSync(runtimeDir)) {
    if (process.platform === 'win32') {
      return path.join(runtimeDir, 'Scripts', 'python.exe')
    }

    return path.join(runtimeDir, 'bin', 'python3')
  }

  if (process.platform === 'win32') {
    return process.env.PYTHON ?? 'python'
  }

  return process.env.PYTHON ?? 'python3'
}

function getBackendWorkingDirectory(): string {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'backend')
  }

  const repoBackend = path.resolve(app.getAppPath(), '..', 'backend')
  if (fs.existsSync(repoBackend)) {
    return repoBackend
  }

  return path.join(app.getAppPath(), 'backend')
}

function startBackend() {
  const pythonExecutable = getPythonExecutable()
  const backendCwd = getBackendWorkingDirectory()
  const args = [
    '-m',
    'uvicorn',
    'app.main:app',
    '--host',
    BACKEND_HOST,
    '--port',
    BACKEND_PORT.toString(),
  ]

  const child = spawn(pythonExecutable, args, {
    cwd: backendCwd,
    env: {
      ...process.env,
      PYTHONPATH: backendCwd,
    },
    stdio: 'inherit',
  })

  child.on('error', (error) => {
    console.error('Failed to start backend process:', error)
  })

  backend = child
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1024,
    height: 768,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
    },
  })

  if (app.isPackaged) {
    const indexPath = path.join(process.resourcesPath, 'frontend-dist', 'index.html')
    win.loadFile(indexPath)
  } else {
    win.loadURL('http://localhost:5173')
    win.webContents.openDevTools({ mode: 'detach' })
  }
}

function stopBackend() {
  if (!backend) {
    return
  }

  backend.kill()
  backend = undefined
}

app.whenReady().then(() => {
  startBackend()
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  stopBackend()
})

app.on('quit', () => {
  stopBackend()
})

process.on('exit', () => {
  stopBackend()
})

process.on('SIGINT', () => {
  stopBackend()
  process.exit(0)
})

process.on('SIGTERM', () => {
  stopBackend()
  process.exit(0)
})
