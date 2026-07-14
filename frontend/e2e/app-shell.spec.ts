import { expect, test } from '@playwright/test'

test('renders the desktop shell with accessible connection controls', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'AI Serial Bridge' })).toBeVisible()
  const languageButton = page.getByRole('button', { name: 'EN' })
  await expect(languageButton).toBeVisible()
  await languageButton.click()
  await expect(page.getByRole('button', { name: '中文' })).toBeVisible()
})
