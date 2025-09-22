import { app, BrowserWindow } from 'electron'
import path from 'path'
import fs from 'fs'
import { spawn, ChildProcess, SpawnOptions } from 'child_process'

const DEV_SERVER_URL = 'http://localhost:5173'
const FRONTEND_ENTRY_SEGMENT_OPTIONS = [
  ['frontend', 'dist', 'index.html'],
  ['frontend-dist', 'index.html'],
]
const BACKEND_HOST = '127.0.0.1'
const BACKEND_PORT = 8000

let backend: ChildProcess | undefined

function resolveRendererEntry(): string | undefined {
  const searchRoots = [
    app.getAppPath(),
    process.resourcesPath,
    path.join(process.resourcesPath, 'app.asar.unpacked'),
    path.resolve(__dirname, '..'),
  ]

  for (const root of searchRoots) {
    for (const segments of FRONTEND_ENTRY_SEGMENT_OPTIONS) {
      const candidate = path.join(root, ...segments)
      if (fs.existsSync(candidate)) {
        return candidate
      }
    }
  }

  return undefined
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

function resolvePackagedPythonRuntimeRoot(): string | undefined {
  const runtimeRoots = [
    path.join(process.resourcesPath, 'python-runtime'),
    path.join(process.resourcesPath, 'app.asar.unpacked', 'python-runtime'),
  ]

  for (const root of runtimeRoots) {
    if (fs.existsSync(root)) {
      return root
    }
  }

  return undefined
}

function resolvePackagedPythonExecutable(runtimeRoot: string): string | undefined {
  const candidates: string[] = []

  if (process.platform === 'win32') {
    candidates.push(path.join(runtimeRoot, 'Scripts', 'python.exe'))
  } else {
    candidates.push(
      path.join(runtimeRoot, 'bin', 'python3'),
      path.join(runtimeRoot, 'bin', 'python'),
    )
  }

  return candidates.find((candidate) => fs.existsSync(candidate))
}

function buildBackendSpawnOptions(moduleRoot: string): SpawnOptions {
  const env = { ...process.env }

  env.PYTHONPATH = [moduleRoot, env.PYTHONPATH]
    .filter((value): value is string => Boolean(value && value.length > 0))
    .join(path.delimiter)

  return {
    env,
    stdio: 'inherit',
    cwd: moduleRoot,
  }
}

function createUvicornModuleArgs(): string[] {
  return [
    '-m',
    'uvicorn',
    'app.main:app',
    '--host',
    BACKEND_HOST,
    '--port',
    BACKEND_PORT.toString(),
  ]
}

function createUvicornCliArgs(): string[] {
  return [
    'app.main:app',
    '--host',
    BACKEND_HOST,
    '--port',
    BACKEND_PORT.toString(),
  ]
}

function startBackend() {
  const backendCwd = getBackendWorkingDirectory()
  const spawnOptions = buildBackendSpawnOptions(backendCwd)
  const moduleArgs = createUvicornModuleArgs()
  const cliArgs = createUvicornCliArgs()

  const launchUvicornFromEnvironment = () => {
    const child = spawn('uvicorn', cliArgs, spawnOptions)
    child.on('error', (error) => {
      console.error('Failed to launch uvicorn from the current environment:', error)
    })
    backend = child
  }

  if (app.isPackaged) {
    const runtimeRoot = resolvePackagedPythonRuntimeRoot()
    const pythonExecutable = runtimeRoot
      ? resolvePackagedPythonExecutable(runtimeRoot)
      : undefined

    if (pythonExecutable) {
      let fallbackInvoked = false
      const child = spawn(pythonExecutable, moduleArgs, spawnOptions)
      child.on('error', (error) => {
        console.error('Failed to launch bundled backend:', error)
        if (!fallbackInvoked) {
          fallbackInvoked = true
          launchUvicornFromEnvironment()
        }
      })
      backend = child
      return
    }

    console.error(
      'Bundled python runtime was not found. Falling back to spawning uvicorn from the environment.',
    )
  }

  launchUvicornFromEnvironment()
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
    const indexPath = resolveRendererEntry()
    if (indexPath) {
      win.loadFile(indexPath)
      return
    }

    console.error('Unable to locate the bundled frontend. Falling back to the dev server URL.')
  } else {
    win.loadURL(DEV_SERVER_URL)
    win.webContents.openDevTools({ mode: 'detach' })
    return
  }

  win.loadURL(DEV_SERVER_URL)
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
