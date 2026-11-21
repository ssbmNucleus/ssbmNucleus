import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'fs'
import { rendererCsp } from './rendererCsp.js'

const backendPort = process.env.VITE_BACKEND_PORT || 5000
const backendTarget = `http://127.0.0.1:${backendPort}`

// Writes the actual port Vite ends up bound to into viewer/.vite-port so that
// Electron (which spawns separately) can discover it instead of guessing 3000.
// Cleared on shutdown so a stale file can't point Electron at a dead port.
function vitePortHandoff() {
  const portFile = path.resolve(__dirname, '.vite-port')
  const cleanup = () => {
    try { fs.unlinkSync(portFile) } catch {}
  }
  return {
    name: 'vite-port-handoff',
    configureServer(server) {
      // Clear any stale file so Electron can't read an outdated port during
      // the gap between Vite booting and binding.
      cleanup()
      server.httpServer?.once('listening', () => {
        const address = server.httpServer.address()
        if (address && typeof address === 'object') {
          fs.writeFileSync(portFile, String(address.port), 'utf8')
        }
      })
      process.on('exit', cleanup)
      process.on('SIGINT', () => { cleanup(); process.exit(0) })
      process.on('SIGTERM', () => { cleanup(); process.exit(0) })
    },
  }
}

export default defineConfig({
  // rendererCsp: the Content-Security-Policy <meta>, built index.html only (rendererCsp.js).
  plugins: [react(), vitePortHandoff(), rendererCsp()],
  // Use relative base path for Electron compatibility
  base: './',
  server: {
    port: 3000,
    strictPort: true, // Fail loudly if 3000 is taken instead of silently shifting
    open: false, // Don't auto-open browser in Electron mode
    proxy: {
      // Proxy /api requests to Flask backend
      '/api': {
        target: backendTarget,
        changeOrigin: true
      },
      // Proxy /storage requests to Flask backend (single source of truth)
      '/storage': {
        target: backendTarget,
        changeOrigin: true
      },
      // Proxy /vanilla requests to Flask backend for vanilla assets
      '/vanilla': {
        target: backendTarget,
        changeOrigin: true
      }
    },
    fs: {
      // Allow serving files from the parent directory
      allow: ['..']
    }
  },
  build: {
    outDir: 'dist',
    // Generate sourcemaps for easier debugging
    sourcemap: true
  },
  publicDir: 'public'
})
