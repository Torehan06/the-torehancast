import { expect, test } from '@playwright/test'

test('the built page loads', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle('The Torehancast')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('The Torehancast')
})
