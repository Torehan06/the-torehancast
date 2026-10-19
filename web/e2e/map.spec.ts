import { expect, test } from '@playwright/test'
import { fixture, serveSummary } from './helpers'

const NO_RACE = ['AZ', 'CA', 'CT', 'HI', 'IN', 'MD', 'MO', 'NV', 'NY', 'ND', 'PA', 'UT', 'VT', 'WA', 'WI']

test.describe('F2 Senate map', () => {
  test('renders all 50 states; states without a 2026 race are neutral and not clickable', async ({ page }) => {
    await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
    await page.goto('/')
    const states = page.locator('svg.map path[data-state]')
    await expect(states).toHaveCount(50)
    const neutral = page.locator('svg.map path.state--neutral')
    await expect(neutral).toHaveCount(15)
    expect((await neutral.evaluateAll((els) => els.map((e) => e.getAttribute('data-state')))).sort()).toEqual(
      [...NO_RACE].sort(),
    )
    for (const code of NO_RACE) {
      const el = page.locator(`path[data-state="${code}"]`)
      await expect(el).not.toHaveAttribute('tabindex')
      await expect(el).not.toHaveAttribute('role', 'button')
    }
    await expect(page.locator('svg.map path.state--race')).toHaveCount(35)
  });

  test('every race is waiting: map still renders, every race says no votes', async ({ page }) => {
    await serveSummary(page, () => ({ status: 200, body: fixture('cases/waiting') }))
    await page.goto('/')
    await expect(page.locator('svg.map path.state--waiting')).toHaveCount(35)
    const items = page.locator('.race-item__detail')
    await expect(items).toHaveCount(35)
    for (const text of await items.allTextContents()) expect(text).toBe('no votes reported for this race')
  });

  test('no request leaves the page origin (data is same-origin in tests)', async ({ page, baseURL }) => {
    const origins = new Set<string>()
    page.on('request', (req) => origins.add(new URL(req.url()).origin))
    await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
    await page.goto('/#GA')
    await expect(page.getByTestId('probabilities')).toBeVisible()
    await page.waitForLoadState('networkidle')
    expect([...origins]).toEqual([new URL(baseURL!).origin])
  });

  test('colour always comes with an explicit number', async ({ page }) => {
    await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
    await page.goto('/')
    const coloured = page.locator('svg.map path[class*="lead-"]')
    // Wait for the summary to render: a one-shot count() could run before it does.
    await expect(coloured.first()).toBeVisible()
    for (const label of await coloured.evaluateAll((els) => els.map((e) => e.getAttribute('aria-label') ?? ''))) {
      expect(label).toMatch(/\d+(\.\d)?%/)
    }
  });

  test('keyboard: tab to a state, Enter opens its panel', async ({ page }) => {
    await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
    await page.goto('/')
    const ga = page.locator('path[data-state="GA"]')
    await ga.focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('heading', { name: /Georgia/ })).toBeVisible()
    await expect(page).toHaveURL(/#GA$/)
    // Neutral states are skipped by Tab: walking the whole map never lands on one.
    const focused = new Set<string>()
    await page.locator('path[data-state="AL"]').focus()
    for (let i = 0; i < 35; i++) {
      focused.add((await page.evaluate(() => document.activeElement?.getAttribute('data-state'))) ?? '')
      await page.keyboard.press('Tab')
    }
    for (const code of NO_RACE) expect(focused.has(code)).toBe(false)
    expect([...focused].filter((c) => c.length === 2)).toHaveLength(35)
  });

  test('390px phone: no horizontal scroll and every race reachable', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
    await page.goto('/')
    await expect(page.locator('.race-item')).toHaveCount(35)
    const { scrollWidth, innerWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }))
    expect(scrollWidth).toBeLessThanOrEqual(innerWidth)
    for (const item of await page.locator('.race-item').all()) {
      await item.scrollIntoViewIfNeeded()
      const box = (await item.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(390)
    }
    await page.locator('[data-race="RI"]').click()
    await expect(page.getByRole('heading', { name: /Rhode Island/ })).toBeInViewport()
  });
})
