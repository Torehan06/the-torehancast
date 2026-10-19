import { expect, test } from '@playwright/test'

test('the built page loads', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle('The TörehanCast')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('The TörehanCast')
})
