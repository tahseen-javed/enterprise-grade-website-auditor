import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Ports and backend origin come from env so nothing is hardcoded in the app.
export default defineConfig(({ mode }) => {
  // loadEnv only reads .env files, so process.env is checked first - that is how
  // the launcher scripts pass the ports through without editing any file.
  const env = loadEnv(mode, process.cwd(), '')
  const pick = (key, fallback) => process.env[key] || env[key] || fallback

  const frontendPort = Number(pick('VITE_FRONTEND_PORT', 5174))
  const backendPort = Number(pick('VITE_BACKEND_PORT', 8001))
  const backendUrl = pick('VITE_API_BASE_URL', `http://127.0.0.1:${backendPort}`)

  return {
    plugins: [react()],
    server: {
      port: frontendPort,
      strictPort: true,
      host: '127.0.0.1',
      proxy: {
        // The dev server proxies /api so the browser only ever talks to one
        // origin. Production builds use VITE_API_BASE_URL instead.
        '/api': {
          target: backendUrl,
          changeOrigin: true,
          ws: false,
          configure: (proxy) => {
            proxy.on('proxyRes', (proxyRes) => {
              // Server-sent events must not be buffered by the proxy.
              if ((proxyRes.headers['content-type'] || '').includes('event-stream')) {
                proxyRes.headers['cache-control'] = 'no-cache, no-transform'
              }
            })
          },
        },
      },
    },
    preview: { port: frontendPort, strictPort: true, host: '127.0.0.1' },
    build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 900 },
  }
})
