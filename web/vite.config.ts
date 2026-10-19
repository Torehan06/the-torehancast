/// <reference types="vitest/config" />
import { createReadStream, existsSync, statSync } from 'node:fs'
import { resolve, sep } from 'node:path'
import type { Connect } from 'vite'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Local preview only: serves web/fixtures/<FIXTURE>/ at /data/replay/, so
 * `npm run dev` shows a populated map with no network. Never part of a build;
 * production reads VITE_DATA_BASE (the GCS bucket).
 *   FIXTURE=cases/waiting npm run dev
 */
function serveFixtures(): Connect.NextHandleFunction {
  const root = resolve(__dirname, 'fixtures', process.env.FIXTURE ?? 'demo')
  return (req, res, next) => {
    const url = (req.url ?? '').split('?')[0]
    if (!url.startsWith('/data/replay/')) return next()
    const file = resolve(root, url.slice('/data/replay/'.length))
    if (!file.startsWith(root + sep) || !existsSync(file) || !statSync(file).isFile()) {
      res.statusCode = 404
      return res.end()
    }
    res.setHeader('content-type', 'application/json')
    res.setHeader('cache-control', 'public, max-age=20')
    createReadStream(file).pipe(res)
  }
}

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'torehancast-fixtures',
      apply: 'serve',
      configureServer: (server) => void server.middlewares.use(serveFixtures()),
      configurePreviewServer: (server) => void server.middlewares.use(serveFixtures()),
    },
  ],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
