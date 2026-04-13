import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import { dirname, resolve } from 'path'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

const pkg = JSON.parse(
  readFileSync(resolve(__dirname, 'package.json'), 'utf-8')
)

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react()],
    define: {
      APP_VERSION: JSON.stringify(pkg.version),
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes('node_modules')) {
              if (id.includes('react-dom') || id.includes('react/')) return 'react-vendor'
              if (id.includes('react-router')) return 'router'
              if (id.includes('@tanstack/react-query')) return 'query'
              if (id.includes('framer-motion')) return 'framer-motion'
              if (id.includes('@phosphor-icons')) return 'phosphor-icons'
              if (id.includes('react-helmet-async')) return 'helmet'
              if (id.includes('axios')) return 'axios'
              // other node_modules → shared vendor chunk
              return 'vendor'
            }
          },
        },
      },
    },
    server: {
      // Allow local/dev hosts while keeping explicit production domain(s).
      // Note: Vite uses `allowedHosts` to protect against DNS rebinding attacks.
      allowedHosts:
        mode === 'development'
          ? ['localhost', '127.0.0.1', '::1', 'host.docker.internal']
          : ['oracletutor.org', '.oracletutor.org'],
      proxy: {
        '/api': {
          target: env.API_PROXY_TARGET || 'http://localhost:8000',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
  }
})
