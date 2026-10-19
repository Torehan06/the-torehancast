import { expect, test } from '@playwright/test'
import { fixture, serveSummary } from './helpers'

test('dark by default; the toggle switches to light and remembers it', async ({ page }) => {
  await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
  await page.goto('/')
  const html = page.locator('html')
  const toggle = page.getByRole('button', { name: 'Dark mode' })
  await expect(html).toHaveAttribute('data-theme', 'dark')
  await expect(toggle).toHaveAttribute('aria-pressed', 'true')
  const darkBg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor)

  await toggle.click()
  await expect(html).toHaveAttribute('data-theme', 'light')
  await expect(toggle).toHaveAttribute('aria-pressed', 'false')
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).not.toBe(darkBg)

  await page.reload()
  await expect(html).toHaveAttribute('data-theme', 'light')
})

test('the theme toggle is visible at phone width', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Dark mode' })).toBeVisible()
})
