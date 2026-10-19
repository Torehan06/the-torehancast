import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { Page, Route } from '@playwright/test'

export const FIXTURES = resolve(import.meta.dirname, '../fixtures')

export function fixture(name: string): Record<string, unknown> {
  return JSON.parse(readFileSync(resolve(FIXTURES, name, 'summary.json'), 'utf8'))
}

/** Serves summary.json from `respond`, which can change between polls. */
export async function serveSummary(page: Page, respond: () => { status: number; body?: unknown }) {
  await page.route('**/data/replay/summary.json', async (route: Route) => {
    const { status, body } = respond()
    await route.fulfill({
      status,
      contentType: 'application/json',
      body: body === undefined ? '' : JSON.stringify(body),
    })
  })
}

export function withGeneratedAt(summary: Record<string, unknown>, iso: string) {
  return { ...summary, generated_at: iso }
}
