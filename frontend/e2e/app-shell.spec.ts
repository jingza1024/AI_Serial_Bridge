import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.route('**/api/config', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ auth_required: false }),
  }))
})

test('renders the desktop shell with accessible connection controls', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'AI Serial Bridge' })).toBeVisible()
  const languageButton = page.getByRole('button', { name: 'EN' })
  await expect(languageButton).toBeVisible()
  await languageButton.click()
  await expect(page.getByRole('button', { name: '中文' })).toBeVisible()
})

test('browses encrypted persistent log sessions with pagination', async ({ page }) => {
  await page.route('**/api/logs', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      available: true,
      encrypted: true,
      ports: [{ port: 'COM14', size: 128, updated_at: 1 }],
    }),
  }))
  await page.route('**/api/logs/COM14/sessions-page?*', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      items: [{ session_id: 'session-1', started_at: 1, ended_at: 2, records: 1 }],
      total: 1,
      offset: 0,
      limit: 10,
    }),
  }))
  await page.route('**/api/logs/COM14?*', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify([{
      kind: 'message',
      source: 'device',
      content: 'boot complete',
      timestamp: 1,
    }]),
  }))

  await page.goto('/')
  await page.getByRole('button', { name: '日志' }).click()
  const dialog = page.getByRole('dialog', { name: '会话日志' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText('已加密存储')).toBeVisible()
  await expect(dialog.getByText(/boot complete/)).toBeVisible()
  await expect(dialog.getByText('1-1 / 1')).toBeVisible()
})
