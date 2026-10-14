import { defineConfig } from 'vitest/config'
import { existsSync, readFileSync } from 'node:fs'
import { parseEnv } from 'node:util'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import defaults from '../config/local.json' with { type: 'json' }

export default defineConfig(() => {
  const envPath = fileURLToPath(new URL('../.env', import.meta.url))
  const env = { ...(existsSync(envPath) ? parseEnv(readFileSync(envPath, 'utf8')) : {}), ...process.env }
  function port(name: string, fallback: number) {
    const value = Number(env[name] || fallback)
    if (!Number.isInteger(value) || value < 1 || value > 65535) throw new Error(`${name} must be between 1 and 65535`)
    return value
  }
  const target = `http://127.0.0.1:${port('CLIENTSCOUT_API_PORT', defaults.api_port)}`
  const frontendPort = port('CLIENTSCOUT_FRONTEND_PORT', defaults.frontend_port)
  const proxy = { '/api': { target, changeOrigin: true } }
  return {
    plugins: [react(), tailwindcss()], envDir: '..',
    define: { __API_TARGET__: JSON.stringify(target) },
    server: { host: '127.0.0.1', port: frontendPort, strictPort: true, proxy },
    preview: { host: '127.0.0.1', port: frontendPort + 1, strictPort: true, proxy },
    test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'], restoreMocks: true },
  }
})
