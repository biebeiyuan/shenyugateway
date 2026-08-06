// 手机视口截图验收：起一个隔离预览（演示数据），在 390×844 触屏模拟下把关键
// 路径走一遍并截图到 admin/.shots/。用法：node scripts/mobile-shots.mjs [port]
// 验收规矩见 AGENTS.md：手机视口是第一现场，截图要人眼过一遍才算「看过」。
import { spawn } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const here = dirname(fileURLToPath(import.meta.url))
const adminDir = join(here, '..')
const repoRoot = join(adminDir, '..')
const outDir = join(adminDir, '.shots')
const port = Number(process.argv[2] || 18130)
const base = `http://127.0.0.1:${port}/admin/?demo=1#/`

const { chromium } = createRequire(join(adminDir, 'package.json'))('playwright')

const server = spawn(
  'python',
  [join(repoRoot, 'scripts/admin_preview.py'), '--port', String(port), '--db-path', `/tmp/shenyu-shots-${port}.db`],
  { cwd: repoRoot, stdio: 'ignore' },
)

async function waitServer() {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/health`)
      if (r.ok) return
    } catch {
      /* 还没起来 */
    }
    await new Promise((r) => setTimeout(r, 500))
  }
  throw new Error('预览服务 60 秒内没起来')
}

async function main() {
  mkdirSync(outDir, { recursive: true })
  await waitServer()
  const browser = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] })
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  page.setDefaultTimeout(15000)
  // 沙箱网络够不着 Google 字体 CDN，挂起的字体会让截图一直等；拦掉用回退衬线
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (route) => route.abort())
  page.on('pageerror', (err) => console.error('[pageerror]', err.message))

  const shot = (name) => page.screenshot({ path: join(outDir, name) })
  // SPA 哈希路由：只改 hash 既不 reload 也不触发路由事件。带上不同 query 整页
  // 重载，应用直接在新路由上出生，最稳。
  const go = async (hash, settleMs = 900) => {
    await page.goto(`http://127.0.0.1:${port}/admin/?demo=1&r=${Date.now()}#${hash}`, { waitUntil: 'load', timeout: 30000 })
    await page.waitForTimeout(settleMs)
  }

  await page.goto(base, { waitUntil: 'load', timeout: 30000 })
  await page.waitForTimeout(1200)
  await shot('01-home.png')

  await go('/mem0')
  await shot('02-mem.png')

  await go('/memory-graph', 2000) // 网的力导布局落定
  await shot('03-graph.png')

  console.log('step: recall tab')
  await page.getByTestId('memory-graph-tab-recall').click()
  console.log('step: fill input')
  await page.getByTestId('memory-graph-recall-input').locator('input').fill('小舟')
  console.log('step: click 想起')
  await page.getByRole('button', { name: '想起', exact: true }).click()
  console.log('step: wait papers')
  await page.waitForSelector('.board-paper', { timeout: 8000 })
  await page.waitForTimeout(1000)
  await shot('04-recall-board.png')

  await page.locator('.board-paper').first().click()
  await page.waitForSelector('.paper-read', { timeout: 5000 })
  await page.waitForTimeout(500)
  await shot('05-recall-paper.png')

  await browser.close()
  console.log(`截图已存到 admin/.shots/（${port} 端口的隔离预览 + 演示数据）`)
}

main()
  .catch((err) => {
    console.error(err)
    process.exitCode = 1
  })
  .finally(() => server.kill())
