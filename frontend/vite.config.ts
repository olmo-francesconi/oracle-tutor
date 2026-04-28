import { resolve } from 'node:path'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  const adminRedirectPlugin = {
    name: 'oracle-tutor-admin-redirect',
    configureServer(server: { middlewares: { use: (handler: (req: { url?: string }, res: { statusCode?: number; setHeader: (name: string, value: string) => void; end: () => void }, next: () => void) => void) => void } }) {
      server.middlewares.use((req, res, next) => {
        if (req.url === '/admin') {
          res.statusCode = 301
          res.setHeader('Location', '/admin/')
          res.end()
          return
        }
        next()
      })
    },
    configurePreviewServer(server: { middlewares: { use: (handler: (req: { url?: string }, res: { statusCode?: number; setHeader: (name: string, value: string) => void; end: () => void }, next: () => void) => void) => void } }) {
      server.middlewares.use((req, res, next) => {
        if (req.url === '/admin') {
          res.statusCode = 301
          res.setHeader('Location', '/admin/')
          res.end()
          return
        }
        next()
      })
    },
  }

  return {
    plugins: [react(), tailwindcss(), adminRedirectPlugin],
    build: {
      rollupOptions: {
        input: {
          public: resolve(__dirname, 'index.html'),
          admin: resolve(__dirname, 'admin/index.html'),
        },
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
      clearMocks: true,
      restoreMocks: true,
    },
    server: {
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
