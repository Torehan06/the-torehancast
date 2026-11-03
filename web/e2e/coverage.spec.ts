import { expect, test } from '@playwright/test'
import { fixture, houseFixture, serveHouse, serveSummary, withGeneratedAt } from './helpers'

const NO_VOTES = 'no votes reported for this race'
const RCV = 'Win probability withheld: ranked-choice simulation is not yet available.'

for (const width of [1280, 390]) for (const theme of ['light', 'dark']) {
  test(`${width}px ${theme}: coverage is distinct throughout both chambers`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.addInitScript((theme) => localStorage.setItem('theme', theme), theme)
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()) })
    await serveSummary(page, () => ({ status: 200, body: { generated_at: new Date().toISOString(), mode: 'live', states: [] } }))
    await serveHouse(page, () => ({ status: 200, body: { generated_at: new Date().toISOString(), mode: 'live', races: [] } }))
    await page.goto('/')
    await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
    await expect(page.locator('svg.map .state--not-tracked')).toHaveCount(26)
    await expect(page.locator('svg.map .state--waiting')).toHaveCount(9)
    for (const code of ['TX', 'KS', 'MI', 'ME', 'AL', 'WY']) {
      await expect(page.locator(`[data-state="${code}"]`)).toHaveAttribute('aria-label', /Not tracked/)
      await expect(page.locator(`[data-state="${code}"] title`)).toHaveText(/Not tracked/)
      await expect(page.locator(`[data-race="${code}"]`)).toContainText('Not tracked')
      await page.locator(`[data-race="${code}"]`).click()
      await expect(page.getByTestId('not-tracked')).toHaveText('Not tracked')
    }
    for (const code of ['GA', 'AK']) {
      await expect(page.locator(`[data-race="${code}"]`)).toContainText(NO_VOTES)
      await page.locator(`[data-race="${code}"]`).click()
      await expect(page.getByTestId('no-votes')).toHaveText(NO_VOTES)
    }
    await expect(page.getByTestId('rcv-unavailable')).toHaveText(RCV)
    await page.getByRole('group', { name: 'Chamber' }).getByRole('button', { name: 'House' }).click()
    await expect(page.locator('.tile--not-tracked')).toHaveCount(341)
    await expect(page.locator('.tile--waiting')).toHaveCount(94)
    for (const key of ['TX-01', 'KS-01', 'MI-01', 'ME-02', 'WY-AL']) {
      await expect(page.locator(`[data-district="${key}"]`)).toHaveAttribute('aria-label', /Not tracked/)
      await page.locator(`[data-district="${key}"]`).click()
      await expect(page.getByTestId('not-tracked')).toHaveText('Not tracked')
      await expect(page.locator(`[data-testid="state-districts"] [data-race="${key}"]`)).toContainText('Not tracked')
    }
    for (const key of ['GA-01', 'AK-AL', 'FL-13', 'OH-03', 'MN-08']) {
      await page.locator(`[data-district="${key}"]`).click()
      await expect(page.getByTestId('no-votes')).toHaveText(NO_VOTES)
    }
    const size = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: innerWidth }))
    expect(size.scroll).toBeLessThanOrEqual(size.width)
    expect(errors).toEqual([])
  })

  test(`${width}px ${theme}: both Alaska races acquire counts without a reload and keep probability withheld`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.addInitScript((theme) => localStorage.setItem('theme', theme), theme)
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()) })
    await page.clock.install({ time: new Date('2026-11-04T05:30:00Z') })
    let published = false
    // A long stale age also exercises the phone header during the view transition.
    const now = () => '2026-11-03T08:30:00Z'
    await serveSummary(page, () => ({ status: 200, body: withGeneratedAt(published ? fixture('demo') : { mode: 'live', states: [] }, now()) }))
    await serveHouse(page, () => ({ status: 200, body: withGeneratedAt(published ? houseFixture() : { mode: 'live', races: [] }, now()) }))
    await page.goto('/#AK')
    await expect(page.getByTestId('no-votes')).toHaveText(NO_VOTES)
    await expect(page.getByTestId('rcv-unavailable')).toHaveText(RCV)
    published = true
    await page.clock.fastForward('00:21')
    await expect(page.getByTestId('results')).toBeVisible()
    await expect(page.getByTestId('rcv-status')).toHaveText(RCV)
    await expect(page.getByTestId('probabilities')).not.toContainText(/\d+%/)
    await expect(page.getByTestId('not-tracked')).toHaveCount(0)
    // Exercise the same transition on the House's independent polling path.
    published = false
    await page.getByRole('group', { name: 'Chamber' }).getByRole('button', { name: 'House' }).click()
    await page.locator('[data-district="AK-AL"]').click()
    await expect(page.getByTestId('no-votes')).toHaveText(NO_VOTES)
    published = true
    await page.clock.fastForward('00:21')
    await expect(page.getByTestId('results')).toContainText('45,120')
    await expect(page.getByTestId('rcv-status')).toHaveText(RCV)
    await expect(page.getByTestId('probabilities')).not.toContainText(/\d+%/)
    const size = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: innerWidth }))
    expect(size.scroll).toBeLessThanOrEqual(size.width)
    expect(errors).toEqual([])
  })
}
