import { execFileSync } from 'node:child_process'
import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'

type BuildInfo = {
  schema: 1
  buildId: string
  revision: string
  builtAt: string
}

function sourceRevision(): string {
  const configured = process.env.PWA_BUILD_COMMIT?.trim()
  if (configured) return configured

  try {
    return execFileSync('git', ['rev-parse', '--verify', 'HEAD'], {
      cwd: process.cwd(),
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim()
  } catch {
    // Docker builds can omit .git. The timestamp still gives the installed
    // client an exact build identity, while the settings sheet exposes this
    // missing source revision instead of pretending it is known.
    return 'unknown'
  }
}

function createBuildInfo(): BuildInfo {
  const revision = sourceRevision()
  const builtAt = new Date().toISOString()
  const compactTime = builtAt.replace(/[-:.]/g, '').replace('T', '-').replace('Z', '')
  const revisionLabel = revision === 'unknown' ? 'source-unknown' : revision.slice(0, 12)

  return {
    schema: 1,
    buildId: `${revisionLabel}-${compactTime}`,
    revision,
    builtAt,
  }
}

function buildInfoAsset(buildInfo: BuildInfo): Plugin {
  return {
    name: 'shenyu-pwa-build-info',
    generateBundle() {
      this.emitFile({
        type: 'asset',
        fileName: 'build-info.json',
        source: `${JSON.stringify(buildInfo, null, 2)}\n`,
      })
    },
  }
}

const buildInfo = createBuildInfo()

export default defineConfig({
  base: '/chat/',
  define: {
    __PWA_BUILD_INFO__: JSON.stringify(buildInfo),
  },
  plugins: [vue(), buildInfoAsset(buildInfo)],
  server: {
    port: 5174,
    proxy: {
      '/v1': 'http://localhost:8010',
      '/api': 'http://localhost:8010',
      '/health': 'http://localhost:8010',
      '/admin': 'http://localhost:8010',
    },
  },
})
