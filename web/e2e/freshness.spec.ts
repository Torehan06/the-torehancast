import { expect, test } from '@playwright/test'
import { fixture, serveSummary, withGeneratedAt } from './helpers'

const T0 = new Date('2026-11-04T02:30:00Z')
const iso = (offsetS: number) => new Date(T0.getTime() + offsetS * 1000).toISOString()

test.describe('F4 stale-data and fetch-failure warnings', () => {
  test('stale banner appears once the newest snapshot is over 120s old, numbers stay', async ({ page }) => {
    await page.clock.install({ time: new Date(T0.getTime() + 10_000) })
    await serveSummary(page, () => ({ status: 200, body: fixture('demo') }))
    await page.goto('/#GA')
    await expect(page.getByTestId('probabilities')).toContainText('87%')
    await expect(page.getByTestId('stale-banner')).toHaveCount(0)

    await page.clock.fastForward('02:00') // 130s after generated_at; the poller keeps serving the same file
    await expect(page.getByTestId('stale-banner')).toBeVisible()
    await expect(page.getByTestId('stale-banner')).toContainText(/2 min \d+s old/)
    await expect(page.getByTestId('probabilities')).toContainText('87%')
  });

  test('fetch failure shows its own state with the data age, and recovers without a reload', async ({ page }) => {
    await page.clock.install({ time: new Date(T0.getTime() + 5_000) })
    let mode: 'ok' | 'down' | 'newer' = 'ok'
    await serveSummary(page, () =>
      mode === 'down'
        ? { status: 500 }
        : { status: 200, body: withGeneratedAt(fixture('demo'), iso(mode === 'newer' ? 45 : 0)) },
    )
    await page.goto('/#GA')
    await expect(page.getByTestId('probabilities')).toContainText('87%')

    mode = 'down'
    await page.clock.fastForward('00:21')
    const failing = page.getByTestId('failing-banner')
    await expect(failing).toBeVisible()
    await expect(failing).toContainText('HTTP 500')
    await expect(page.getByTestId('probabilities')).toContainText('87%') // last numbers kept

    mode = 'newer'
    await page.clock.fastForward('00:21')
    await expect(failing).toHaveCount(0)
    await expect(page.getByTestId('stale-banner')).toHaveCount(0)
    await expect(page.getByTestId('freshness')).toContainText(/Updated \d+s ago/)
  });

  test('a first fetch that fails says so instead of showing an empty map as if quiet', async ({ page }) => {
    await serveSummary(page, () => ({ status: 503 }))
    await page.goto('/')
    await expect(page.getByTestId('failing-banner')).toContainText('HTTP 503')
  });

  test('malformed JSON counts as a failed fetch', async ({ page }) => {
    await serveSummary(page, () => ({ status: 200, body: { hello: 'world' } }))
    await page.goto('/')
    await expect(page.getByTestId('failing-banner')).toBeVisible()
  });

  test('an older snapshot never replaces a newer one', async ({ page }) => {
    await page.clock.install({ time: new Date(T0.getTime() + 60_000) })
    let first = true
    await serveSummary(page, () => {
      const body = first ? withGeneratedAt(fixture('demo'), iso(50)) : withGeneratedAt(fixture('cases/waiting'), iso(0))
      first = false
      return { status: 200, body }
    })
    await page.goto('/#GA')
    await expect(page.getByTestId('probabilities')).toBeVisible()
    await page.clock.fastForward('00:21')
    await expect(page.getByTestId('probabilities')).toBeVisible()
  });
})
