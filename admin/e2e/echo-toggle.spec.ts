import { expect, test, type Page } from '@playwright/test'

const BASE_URL = process.env.E2E_BASE_URL || `http://127.0.0.1:${process.env.E2E_PORT || 18110}`
const ORIGIN = new URL(BASE_URL).origin
const TOKEN = process.env.E2E_GATEWAY_TOKEN || 'shenyu-e2e-smoke'
const PROMPT = '只用于测试的回响提示词。\n保留第二行。'

test.beforeEach(async ({ context, page }) => {
  await context.addCookies([{ name: 'shenyu_token', value: TOKEN, url: ORIGIN, sameSite: 'Lax' }])
  await page.addInitScript((token) => localStorage.setItem('shenyu_token', token), TOKEN)
})

async function mockConfig(page: Page, prompt: string, failSave = false) {
  const response = await page.request.get(new URL('/api/config/full', BASE_URL).toString())
  expect(response.ok()).toBeTruthy()
  let saved = { ...await response.json(), enable_echo: true, echo_prompt: prompt, echo_retention_turns: 4 }
  const patches: Record<string, unknown>[] = []
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('requestfailed', (request) => {
    if (new URL(request.url()).origin === ORIGIN && ['document', 'script', 'stylesheet'].includes(request.resourceType())) {
      errors.push(`Failed asset: ${request.url()}`)
    }
  })
  page.on('response', (response) => {
    if (new URL(response.url()).origin === ORIGIN && response.status() >= 400 && ['document', 'script', 'stylesheet'].includes(response.request().resourceType())) {
      errors.push(`Failed asset: ${response.url()}`)
    }
  })
  await page.route('**/api/config/full', (route) => route.fulfill({ json: saved }))
  await page.route('**/api/config', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    const patch = route.request().postDataJSON()
    patches.push(patch)
    if (failSave) return route.fulfill({ status: 500, json: { detail: 'simulated save failure' } })
    saved = { ...saved, ...patch }
    await route.fulfill({ json: { ok: true, changed: Object.keys(patch), config: saved } })
  })
  return { patches, errors }
}

async function save(page: Page) {
  const response = page.waitForResponse((response) =>
    new URL(response.url()).pathname === '/api/config' && response.request().method() === 'POST')
  await page.getByRole('button', { name: '保存配置', exact: true }).click()
  return response
}

for (const width of [390, 1280]) {
  for (const [label, promptText] of [['nonempty', PROMPT], ['empty', '']]) {
    test(`echo toggle keeps saved text across save and reload (${width}, ${label})`, async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 844 })
      const { patches, errors } = await mockConfig(page, promptText)
      await page.goto(new URL('/admin/#/config', BASE_URL).toString())
      const toggle = page.getByTestId('config-enable-echo')
      const prompt = page.getByTestId('config-echo-prompt').locator('textarea')
      const retention = page.getByTestId('config-echo-retention-turns').locator('input')
      const card = page.getByTestId('config-echo-card')
      await expect(toggle).toHaveAttribute('aria-checked', 'true')
      await expect(prompt).toHaveValue(promptText)
      await expect(prompt).toBeEnabled()
      await expect(retention).toHaveValue('4')
      await toggle.click()
      await expect(toggle).toHaveAttribute('aria-checked', 'false')
      await expect(prompt).toBeDisabled()
      await expect(retention).toBeDisabled()
      expect(patches).toHaveLength(0)
      expect((await save(page)).ok()).toBeTruthy()
      expect(patches[0]).toMatchObject({ enable_echo: false, echo_prompt: promptText, echo_retention_turns: 4 })
      await page.reload()
      await expect(toggle).toHaveAttribute('aria-checked', 'false')
      await expect(prompt).toHaveValue(promptText)
      await expect(prompt).toBeDisabled()
      await expect(retention).toHaveValue('4')
      if (label === 'nonempty') {
        await card.screenshot({ path: testInfo.outputPath(`echo-off-${width}.png`) })
      }
      await toggle.focus()
      await page.keyboard.press('Space')
      await expect(toggle).toHaveAttribute('aria-checked', 'true')
      await expect(prompt).toBeEnabled()
      await expect(retention).toBeEnabled()
      expect((await save(page)).ok()).toBeTruthy()
      expect(patches[1]).toMatchObject({ enable_echo: true, echo_prompt: promptText, echo_retention_turns: 4 })
      await page.reload()
      await expect(toggle).toHaveAttribute('aria-checked', 'true')
      await expect(prompt).toHaveValue(promptText)
      if (label === 'nonempty') {
        await card.screenshot({ path: testInfo.outputPath(`echo-on-${width}.png`) })
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy()
      expect(errors).toEqual([])
    })
  }
}

test('echo toggle failed save does not persist or report success', async ({ page }) => {
  const { patches, errors } = await mockConfig(page, PROMPT, true)
  await page.goto(new URL('/admin/#/config', BASE_URL).toString())
  const toggle = page.getByTestId('config-enable-echo')
  await expect(toggle).toHaveAttribute('aria-checked', 'true')
  await toggle.click()
  expect((await save(page)).status()).toBe(500)
  await expect(page.getByText('Request failed with status code 500', { exact: true })).toBeVisible()
  await expect(page.getByText(/^Saved \d+ fields?$/)).toHaveCount(0)
  expect(patches[0].enable_echo).toBe(false)
  await page.reload()
  await expect(toggle).toHaveAttribute('aria-checked', 'true')
  await expect(page.getByTestId('config-echo-prompt').locator('textarea')).toHaveValue(PROMPT)
  expect(errors).toEqual([])
})
