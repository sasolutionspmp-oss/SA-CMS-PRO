import { app, BrowserWindow } from 'electron'
import path from 'path'
import fs from 'fs'
import { spawn, ChildProcess, SpawnOptionsWithoutStdio } from 'child_process'

const DEV_SERVER_URL = 'http://localhost:5173'
const FRONTEND_ENTRY_SEGMENTS = ['frontend', 'dist', 'index.html']

let backend: ChildProcess | undefined

function resolveRendererEntry(): string | undefined {
  const searchRoots = [
    app.getAppPath(),
    process.resourcesPath,
    path.join(process.resourcesPath, 'app.asar.unpacked'),
    path.resolve(__dirname, '..'),
  ]

  for (const root of searchRoots) {
    const candidate = path.join(root, ...FRONTEND_ENTRY_SEGMENTS)
    if (fs.existsSync(candidate)) {
      return candidate
    }
  }

  return undefined
}

function resolvePythonModuleRoot(): string | undefined {
  const candidateRoots = [
    path.resolve(__dirname, '..'),
    process.resourcesPath,
    path.join(process.resourcesPath, 'app.asar.unpacked'),
  ]

  for (const candidate of candidateRoots) {
    if (candidate.endsWith('.asar')) {
      continue
    }

    if (fs.existsSync(path.join(candidate, 'app', '__init__.py'))) {
      return candidate
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

function buildBackendSpawnOptions(moduleRoot?: string): SpawnOptionsWithoutStdio {
  const env = { ...process.env }

  if (moduleRoot) {
    env.PYTHONPATH = [moduleRoot, env.PYTHONPATH]
      .filter((value): value is string => Boolean(value && value.length > 0))
      .join(path.delimiter)
  }

  const options: SpawnOptionsWithoutStdio = {
    env,
    stdio: 'inherit',
  }

  if (moduleRoot) {
    options.cwd = moduleRoot
  }

  return options
}

function startBackend() {
  const moduleRoot = resolvePythonModuleRoot()
  const spawnOptions = buildBackendSpawnOptions(moduleRoot)

  if (app.isPackaged) {
    const runtimeRoot = resolvePackagedPythonRuntimeRoot()
    const pythonExecutable = runtimeRoot
      ? resolvePackagedPythonExecutable(runtimeRoot)
      : undefined

    if (pythonExecutable) {
      backend = spawn(pythonExecutable, ['-m', 'uvicorn', 'app.main:app'], spawnOptions)
      backend.on('error', (error) => {
        console.error('Failed to launch bundled backend:', error)
      })
      return
    }

    console.error(
      'Bundled python runtime was not found. Falling back to spawning uvicorn from the environment.',
    )
  }

  backend = spawn('uvicorn', ['app.main:app'], spawnOptions)
  backend.on('error', (error) => {
    console.error('Failed to launch uvicorn from the current environment:', error)
  })
}

function createWindow() {
  const win = new BrowserWindow({
    width: 800,
    height: 600,
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
  }

  win.loadURL(DEV_SERVER_URL)
}

app.whenReady().then(() => {
  startBackend()
  createWindow()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('quit', () => {
  backend?.kill()
})
