import { expect, test, type Page } from '@playwright/test'
import { fixture, houseFixture, serveHouse, serveSummary, withGeneratedAt } from './helpers'

const NO_VOTES = 'no votes reported for this race'
const T0 = new Date('2026-11-04T02:30:00Z')
const iso = (offsetS: number) => new Date(T0.getTime() + offsetS * 1000).toISOString()
const tiles = (page: Page) => page.locator('[data-district]')
const toggle = (page: Page, name: 'Senate' | 'House') => page.getByRole('group', { name: 'Chamber' }).getByRole('button', { name })

/** Counts house.json requests, so a test can show when the page does and doesn't poll it. */
function countHouseRequests(page: Page) {
  const seen = { count: 0 }
  page.on('request', (req) => {
    if (req.url().endsWith('/house.json')) seen.count += 1
  })
  return seen
}

test.describe('F5 House view', () => {
  test('the toggle switches views and the hash follows; Senate counts are untouched', async ({ page }) => {
    await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
    await serveHouse(page, () => ({ status: 200, body: houseFixture() }))
    await page.goto('/')
    await expect(toggle(page, 'Senate')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('svg.map path[data-state]')).toHaveCount(50)
    await expect(tiles(page)).toHaveCount(0)

    await toggle(page, 'House').click()
    await expect(toggle(page, 'House')).toHaveAttribute('aria-pressed', 'true')
    await expect(tiles(page)).toHaveCount(435)
    await expect(page.locator('svg.map')).toHaveCount(0)
    await expect(page).toHaveURL(/#house$/)

    await toggle(page, 'Senate').click()
    await expect(page.locator('svg.map path[data-state]')).toHaveCount(50)
    await expect(page.locator('svg.map path.state--race')).toHaveCount(35)
    await expect(page).not.toHaveURL(/#/)
  })

  test('house.json is polled only while the House view is open', async ({ page }) => {
    await page.clock.install({ time: T0 })
    const requests = countHouseRequests(page)
    await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
    await serveHouse(page, () => ({ status: 200, body: houseFixture() }))
    await page.goto('/')
    await expect(page.locator('svg.map path.state--race')).toHaveCount(35)
    await page.clock.fastForward('01:00')
    await page.waitForLoadState('networkidle')
    expect(requests.count).toBe(0)

    await toggle(page, 'House').click()
    await expect(tiles(page)).toHaveCount(435)
    await expect.poll(() => requests.count).toBe(1)
    await page.clock.fastForward('00:21')
    await expect.poll(() => requests.count).toBe(2)

    await toggle(page, 'Senate').click()
    await expect(page.locator('svg.map')).toBeVisible()
    await page.clock.fastForward('01:00')
    await page.waitForLoadState('networkidle')
    expect(requests.count).toBe(2)
  })

  test('a direct link to a district opens the House view, its panel, and polls', async ({ page }) => {
    const requests = countHouseRequests(page)
    await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
    await serveHouse(page, () => ({ status: 200, body: houseFixture() }))
    await page.goto('/#NC-01')
    await expect(toggle(page, 'House')).toHaveAttribute('aria-pressed', 'true')
    await expect(page.getByRole('heading', { name: /North Carolina's 1st District/ })).toBeVisible()
    await expect(page.getByTestId('probabilities')).toContainText('62%')
    expect(requests.count).toBeGreaterThan(0)
  })

  test('a missing house.json is fine: every tile says no votes and no banner appears', async ({ page }) => {
    await page.clock.install({ time: new Date(T0.getTime() + 10_000) })
    await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
    await serveHouse(page, () => ({ status: 404 }))
    await page.goto('/#house')
    await expect(tiles(page)).toHaveCount(435)
    await expect(page.locator('.tile--waiting')).toHaveCount(435)
    await page.clock.fastForward('00:21') // a second 404 changes nothing
    await expect(page.locator('.tile--waiting')).toHaveCount(435)
    for (const label of await tiles(page).evaluateAll((els) => els.map((e) => e.getAttribute('aria-label') ?? ''))) {
      expect(label).toContain(NO_VOTES)
    }
    await expect(page.getByTestId('failing-banner')).toHaveCount(0)
    await expect(page.getByTestId('stale-banner')).toHaveCount(0)
    await expect(page.getByTestId('freshness')).toContainText(/Updated \d+s ago/)

    await page.locator('[data-district="PA-07"]').click()
    await expect(page.getByTestId('no-votes')).toHaveText(NO_VOTES)
  })

  test('house.json appearing later fills the tiles without a reload', async ({ page }) => {
    await page.clock.install({ time: new Date(T0.getTime() + 5_000) })
    let published = false
    await serveSummary(page, () => ({ status: 200, body: withGeneratedAt(fixture('demo'), iso(0)) }))
    await serveHouse(page, () => (published ? { status: 200, body: withGeneratedAt(houseFixture(), iso(0)) } : { status: 404 }))
    await page.goto('/#house')
    await expect(page.locator('.tile--waiting')).toHaveCount(435)
    published = true
    await page.clock.fastForward('00:21')
    await expect(page.locator('[data-district="NC-01"]')).toHaveClass(/lead-D/)
  })

  test('tiles are coloured by leader and always carry the number; absent races stay hatched', async ({ page }) => {
    await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
    await serveHouse(page, () => ({ status: 200, body: houseFixture() }))
    await page.goto('/#house')
    await expect(page.locator('[data-district="NC-01"]')).toHaveClass(/lead-D/)
    await expect(page.locator('[data-district="IA-01"]')).toHaveClass(/lead-R/)
    await expect(page.locator('[data-district="VT-AL"]')).toHaveClass(/lead-other/)
    await expect(page.locator('[data-district="WY-AL"]')).toHaveClass(/tile--waiting/)
    await expect(page.locator('[data-district="TX-01"]')).toHaveClass(/tile--noleader/)
    const coloured = page.locator('[data-district][class*="lead-"]')
    for (const label of await coloured.evaluateAll((els) => els.map((e) => e.getAttribute('aria-label') ?? ''))) {
      expect(label).toMatch(/\d+(\.\d)?%/)
    }
  })

  test('keyboard: one tab stop, arrows move, Enter opens the panel, closing returns to the tile', async ({ page }) => {
    await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
    await serveHouse(page, () => ({ status: 200, body: houseFixture() }))
    await page.goto('/#house')
    await expect(tiles(page)).toHaveCount(435)
    await expect(page.locator('[data-district][tabindex="0"]')).toHaveCount(1)

    await toggle(page, 'House').focus()
    await page.keyboard.press('Tab')
    const active = () => page.evaluate(() => document.activeElement?.getAttribute('data-district'))
    const first = await active()
    expect(first).toBeTruthy()
    await page.keyboard.press('ArrowDown')
    const second = await active()
    expect(second).toBeTruthy()
    expect(second).not.toBe(first)

    await page.keyboard.press('Enter')
    await expect(page.getByTestId('race-panel')).toBeVisible()
    await expect(page.locator('#panel-title')).toBeFocused()
    await expect(page).toHaveURL(new RegExp(`#${second}$`))

    await page.getByRole('button', { name: 'Close race details' }).click()
    await expect(page.getByTestId('race-panel')).toHaveCount(0)
    await expect(page).toHaveURL(/#house$/)
    await expect.poll(active).toBe(second)

    // One Tab from the map leaves it, instead of walking 435 squares.
    await page.keyboard.press('Tab')
    expect(await active()).toBeFalsy()
  })

  test('390px phone: no horizontal scroll, and every district reachable through the state picker', async ({ page }) => {
    test.slow() // 50 picker selections
    await page.setViewportSize({ width: 390, height: 844 })
    await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
    await serveHouse(page, () => ({ status: 200, body: houseFixture() }))
    await page.goto('/#house')
    await expect(tiles(page)).toHaveCount(435)
    const noHorizontalScroll = async () => {
      const { scrollWidth, innerWidth } = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth,
      }))
      expect(scrollWidth).toBeLessThanOrEqual(innerWidth)
    }
    await noHorizontalScroll()

    const picker = page.getByTestId('state-picker')
    const states = await picker.locator('option').evaluateAll((els) => els.map((e) => (e as HTMLOptionElement).value).filter(Boolean))
    expect(states).toHaveLength(50)
    let total = 0
    for (const state of states) {
      await picker.selectOption(state)
      const rows = page.getByTestId('state-districts').locator('.race-item')
      total += await rows.count()
    }
    expect(total).toBe(435)

    await picker.selectOption('CA')
    await noHorizontalScroll() // the state with the most rows
    for (const row of await page.getByTestId('state-districts').locator('.race-item').all()) {
      const box = (await row.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(390)
    }

    await picker.selectOption('NC')
    await page.locator('[data-testid="state-districts"] [data-race="NC-01"]').click()
    await expect(page.getByRole('heading', { name: /North Carolina's 1st District/ })).toBeInViewport()
    await noHorizontalScroll() // the panel, with its results table
  })

  test('390px phone: the ranked-choice panel fits with no horizontal scroll', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
    await serveHouse(page, () => ({ status: 200, body: houseFixture() }))
    await page.goto('/#ME-02')
    await expect(page.getByTestId('probabilities')).toContainText('54%')
    const { scrollWidth, innerWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      innerWidth: window.innerWidth,
    }))
    expect(scrollWidth).toBeLessThanOrEqual(innerWidth)
  })

  test('no request leaves the page origin in the House view', async ({ page, baseURL }) => {
    const origins = new Set<string>()
    page.on('request', (req) => origins.add(new URL(req.url()).origin))
    await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
    await serveHouse(page, () => ({ status: 200, body: houseFixture() }))
    await page.goto('/#NC-01')
    await expect(page.getByTestId('probabilities')).toBeVisible()
    await page.waitForLoadState('networkidle')
    expect([...origins]).toEqual([new URL(baseURL!).origin])
  })
})

test.describe('F5 stale-data and failure warnings', () => {
  test('stale house.json raises the stale banner and keeps the numbers', async ({ page }) => {
    await page.clock.install({ time: new Date(T0.getTime() + 10_000) })
    await serveSummary(page, () => ({ status: 200, body: withGeneratedAt(fixture('demo'), iso(0)) }))
    await serveHouse(page, () => ({ status: 200, body: withGeneratedAt(houseFixture(), iso(0)) }))
    await page.goto('/#NC-01')
    await expect(page.getByTestId('probabilities')).toContainText('62%')
    await expect(page.getByTestId('stale-banner')).toHaveCount(0)

    await page.clock.fastForward('02:00')
    await expect(page.getByTestId('stale-banner')).toBeVisible()
    await expect(page.getByTestId('stale-banner')).toContainText(/2 min \d+s old/)
    await expect(page.getByTestId('probabilities')).toContainText('62%')
  })

  test('house.json going stale while summary.json keeps updating still warns in the House view', async ({ page }) => {
    await page.clock.install({ time: new Date(T0.getTime() + 10_000) })
    await serveSummary(page, () => ({ status: 200, body: withGeneratedAt(fixture('demo'), new Date().toISOString()) }))
    await serveHouse(page, () => ({ status: 200, body: withGeneratedAt(houseFixture(), iso(0)) }))
    await page.goto('/#house')
    await expect(page.locator('[data-district="NC-01"]')).toHaveClass(/lead-D/)
    await page.clock.fastForward('02:00')
    await expect(page.getByTestId('stale-banner')).toBeVisible()
  })

  test('with house.json missing, a dead publisher still shows the stale banner', async ({ page }) => {
    await page.clock.install({ time: new Date(T0.getTime() + 10_000) })
    await serveSummary(page, () => ({ status: 200, body: withGeneratedAt(fixture('demo'), iso(0)) }))
    await serveHouse(page, () => ({ status: 404 }))
    await page.goto('/#house')
    await expect(page.locator('.tile--waiting')).toHaveCount(435)
    await page.clock.fastForward('02:00')
    await expect(page.getByTestId('stale-banner')).toBeVisible()
  })

  test('a failing house.json shows the failure banner, keeps numbers, and recovers', async ({ page }) => {
    await page.clock.install({ time: new Date(T0.getTime() + 5_000) })
    let mode: 'ok' | 'down' | 'newer' = 'ok'
    await serveSummary(page, () => ({ status: 200, body: withGeneratedAt(fixture('demo'), iso(0)) }))
    await serveHouse(page, () =>
      mode === 'down' ? { status: 500 } : { status: 200, body: withGeneratedAt(houseFixture(), iso(mode === 'newer' ? 45 : 0)) },
    )
    await page.goto('/#NC-01')
    await expect(page.getByTestId('probabilities')).toContainText('62%')

    mode = 'down'
    await page.clock.fastForward('00:21')
    const failing = page.getByTestId('failing-banner')
    await expect(failing).toBeVisible()
    await expect(failing).toContainText('HTTP 500')
    await expect(page.getByTestId('probabilities')).toContainText('62%')

    mode = 'newer'
    await page.clock.fastForward('00:21')
    await expect(failing).toHaveCount(0)
    await expect(page.getByTestId('stale-banner')).toHaveCount(0)
  })

  test('returning to the House view does not flash a stale banner over a kept snapshot', async ({ page }) => {
    await page.clock.install({ time: new Date(T0.getTime() + 5_000) })
    let now = iso(0)
    let release = () => {}
    let hold = false
    let held = false
    await serveSummary(page, () => ({ status: 200, body: withGeneratedAt(fixture('demo'), now) }))
    await page.route('**/data/replay/house.json', async (route) => {
      if (hold) {
        await new Promise<void>((done) => {
          release = done
          held = true
        })
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(withGeneratedAt(houseFixture(), now)) })
    })
    await page.goto('/#house')
    await expect(page.locator('[data-district="NC-01"]')).toHaveClass(/lead-D/)

    await toggle(page, 'Senate').click()
    now = iso(300)
    await page.clock.fastForward('05:00') // the kept house.json is now five minutes old
    await expect(page.getByTestId('freshness')).toContainText(/Updated \d+s ago/)

    hold = true
    await toggle(page, 'House').click()
    await expect(tiles(page)).toHaveCount(435)
    await expect.poll(() => held).toBe(true) // the first fetch back is still out
    await expect(page.getByTestId('stale-banner')).toHaveCount(0)
    await expect(page.getByTestId('failing-banner')).toHaveCount(0)
    hold = false
    release()
    await expect(page.getByTestId('freshness')).toContainText(/Updated \d+s ago/)
    await expect(page.getByTestId('stale-banner')).toHaveCount(0)
  })

  test('a failing house.json never raises a banner over the Senate view', async ({ page }) => {
    await page.clock.install({ time: new Date(T0.getTime() + 5_000) })
    await serveSummary(page, () => ({ status: 200, body: withGeneratedAt(fixture('demo'), iso(0)) }))
    await serveHouse(page, () => ({ status: 500 }))
    await page.goto('/#house')
    await expect(page.getByTestId('failing-banner')).toContainText('HTTP 500')
    await toggle(page, 'Senate').click()
    await expect(page.getByTestId('failing-banner')).toHaveCount(0)
  })
})
