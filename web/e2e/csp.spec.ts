import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'
import { fixture, houseFixture, serveHouse, serveSummary } from './helpers'

const hosting = JSON.parse(readFileSync(resolve(import.meta.dirname, '../../firebase.json'), 'utf8')).hosting
const headers = hosting.headers.find((rule: { source: string }) => rule.source === '**').headers
const policy = headers.find((header: { key: string }) => header.key === 'Content-Security-Policy').value as string

test('production CSP: JSON validation emits no eval violation or console error', async ({ page }) => {
  const errors: string[] = []
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('pageerror', (error) => errors.push(error.message))
  await page.addInitScript(() => {
    const monitored = window as typeof window & { cspViolations: string[] }
    monitored.cspViolations = []
    document.addEventListener('securitypolicyviolation', (event) => monitored.cspViolations.push(`${event.effectiveDirective}: ${event.blockedURI}`))
  })
  // Apply the real Hosting header to the production HTML; keep fixture data local.
  await page.route('**/*', async (route) => {
    if (route.request().resourceType() !== 'document') return route.fallback()
    const response = await route.fetch()
    await route.fulfill({ response, headers: { ...response.headers(), 'content-security-policy': policy } })
  })
  await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
  await serveHouse(page, () => ({ status: 200, body: houseFixture() }))
  await page.goto('/#GA')
  await expect(page.getByTestId('probabilities')).toContainText('87%')
  await page.getByRole('group', { name: 'Chamber' }).getByRole('button', { name: 'House' }).click()
  await page.locator('[data-district="NC-01"]').click()
  await expect(page.getByTestId('probabilities')).toContainText('62%')
  expect(await page.evaluate(() => (window as typeof window & { cspViolations: string[] }).cspViolations)).toEqual([])
  expect(errors).toEqual([])
})
