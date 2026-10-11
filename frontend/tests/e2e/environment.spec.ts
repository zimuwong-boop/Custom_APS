import { expect, test } from '@playwright/test'

test('empty workspace and desktop layouts', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '工作总览', exact: true })).toBeVisible()
  await expect(page.getByText('暂无生产批次，确认排产后将在这里显示')).toBeVisible()
  await expect(page.locator('.el-loading-mask')).toHaveCount(0)
  await page.screenshot({ path: '../Docs/screenshots/01-empty-workspace.png', fullPage: true })
  await page.setViewportSize({ width: 1920, height: 1080 })
  await expect(page.locator('.el-loading-mask')).toHaveCount(0)
  await page.screenshot({ path: '../Docs/screenshots/02-wide-workspace.png', fullPage: true })
  expect(errors).toEqual([])
})

test('UI creates material, validates, edits, and deletes without login', async ({ page }) => {
  await page.goto('/#items')
  await page.getByRole('button', { name: '＋ 新建物料' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('物料编码').fill('TEMP-UI')
  await dialog.getByLabel('物料名称').fill('临时测试物料')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByText('已保存', { exact: true })).toBeVisible()
  const row = page.getByRole('row').filter({ hasText: 'TEMP-UI' })
  await row.getByRole('button', { name: '编辑', exact: true }).click()
  await dialog.getByLabel('物料名称').fill('修改后的临时物料')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  await expect(row).toContainText('修改后的临时物料')
  await row.getByRole('button', { name: '删除', exact: true }).click()
  await page.getByRole('button', { name: '确定', exact: true }).click()
  await expect(row).toHaveCount(0)
})
