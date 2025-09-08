import { app, BrowserWindow } from 'electron'
import path from 'path'
import { spawn, ChildProcessWithoutNullStreams } from 'child_process'

let backend: ChildProcessWithoutNullStreams | undefined

function createWindow() {
  const win = new BrowserWindow({
    width: 800,
    height: 600,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
    },
  })
  win.loadURL('http://localhost:5173')
}

app.whenReady().then(() => {
  backend = spawn('uvicorn', ['app.main:app'])
  createWindow()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('quit', () => {
  backend?.kill()
})
