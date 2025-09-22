#!/usr/bin/env node
const fs = require('fs')
const path = require('path')

const root = path.resolve(__dirname, '..')
const repoRoot = path.resolve(root, '..')

const frontendBuild = path.join(repoRoot, 'frontend', 'dist')
const desktopFrontend = path.join(root, 'frontend-dist')
const backendSource = path.join(repoRoot, 'backend')
const desktopBackend = path.join(root, 'backend')

async function removeIfExists(target) {
  await fs.promises.rm(target, { recursive: true, force: true })
}

async function copyRecursive(from, to) {
  await fs.promises.mkdir(path.dirname(to), { recursive: true })
  await fs.promises.cp(from, to, { recursive: true })
}

async function copyFrontend() {
  if (!fs.existsSync(frontendBuild)) {
    throw new Error('Missing frontend build output. Run "npm --prefix frontend run build" before packaging the desktop app.')
  }
  await removeIfExists(desktopFrontend)
  await fs.promises.mkdir(desktopFrontend, { recursive: true })
  await fs.promises.cp(frontendBuild, desktopFrontend, { recursive: true })
}

async function copyBackend() {
  await removeIfExists(desktopBackend)
  await fs.promises.mkdir(desktopBackend, { recursive: true })
  const backendItems = ['app', 'alembic', 'alembic.ini', 'sa_cms_pro.db']
  for (const item of backendItems) {
    const from = path.join(backendSource, item)
    if (!fs.existsSync(from)) {
      continue
    }
    const to = path.join(desktopBackend, item)
    await copyRecursive(from, to)
  }
}

async function main() {
  await copyFrontend()
  await copyBackend()
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
