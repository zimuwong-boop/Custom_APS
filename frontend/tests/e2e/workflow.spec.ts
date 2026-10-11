import { expect, test } from '@playwright/test'

// All fixtures here are temporary and live only in the e2e server's disposable SQLite DB.
test('sales → split / merge → batches → dependency gate → 36% → completion → trace', async ({
  page,
  request,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  const bootstrap = await (await request.get('/api/v1/bootstrap')).json()
  let epoch = bootstrap.data.dataset_epoch
  const csrf = bootstrap.data.csrf_token
  const write = async (path: string, body: object) => {
    const response = await request.post('/api/v1/' + path, {
      data: { ...body, dataset_epoch: epoch },
      headers: { 'X-CSRFToken': csrf, 'Idempotency-Key': crypto.randomUUID() },
    })
    const result = await response.json()
    expect(response.ok(), JSON.stringify(result)).toBeTruthy()
    epoch = result.meta.dataset_epoch
    return result.data
  }
  const units = await (await request.get('/api/v1/units')).json()
  const raw = await write('items', {
    code: 'TEMP-R',
    name: '临时原料',
    type: 'RAW',
    unit_id: units.data.results.find((u: { code: string }) => u.code === 'PCS').id,
  })
  const semi = await write('items', {
    code: 'TEMP-S',
    name: '临时半成品',
    type: 'SEMI',
    unit_id: raw.unit_id,
  })
  const sb = await write('boms', {
    item_id: semi.id,
    revision: 'V1',
    base_quantity: '1',
    lines: [{ component_item_id: raw.id, quantity: '1', child_bom_id: null }],
  })
  await write(`boms/${sb.id}/activate`, { expected_version: sb.version })
  const finished = await write('items', {
    code: 'TEMP-F',
    name: '临时成品',
    type: 'FINISHED',
    unit_id: raw.unit_id,
  })
  const fb = await write('boms', {
    item_id: finished.id,
    revision: 'V1',
    base_quantity: '1',
    lines: [{ component_item_id: semi.id, child_bom_id: sb.id, quantity: '2' }],
  })
  await write(`boms/${fb.id}/activate`, { expected_version: fb.version })
  await page.goto('/#sales-orders')
  await page.getByRole('button', { name: '＋ 新建销售单' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('销售单号').fill('TEMP-SALE')
  await dialog.getByLabel('客户名称').fill('临时测试客户')
  await dialog.getByRole('button', { name: '＋ 添加行' }).click()
  await dialog.locator('.line-form .el-select').first().click()
  await page.getByRole('option', { name: 'TEMP-F · 临时成品', exact: true }).click()
  await dialog.locator('.line-form .el-input input').fill('2')
  await dialog.getByRole('button', { name: '保存', exact: true }).click()
  const salesRow = page.getByRole('row').filter({ hasText: 'TEMP-SALE' })
  await salesRow.getByRole('button', { name: '确认需求', exact: true }).click()
  await expect(salesRow).toContainText('已确认')
  await page.locator('nav').getByRole('button', { name: '排产工作台' }).click()
  await expect(page.getByText('临时成品 / V1')).toBeVisible()
  const rootRow = page.getByRole('row').filter({ hasText: '临时成品 / V1' })
  await rootRow.getByRole('button', { name: '拆单', exact: true }).click()
  await page.getByRole('dialog', { name: '拆分生产单' }).getByRole('textbox').fill('1,1')
  await page.getByRole('button', { name: '确定', exact: true }).click()
  await expect(page.getByRole('row').filter({ hasText: '临时成品 / V1' })).toHaveCount(2)
  const rootRows = page.getByRole('row').filter({ hasText: '临时成品 / V1' })
  await rootRows.first().getByRole('button', { name: '合单', exact: true }).click()
  await page.getByRole('dialog', { name: '合并生产单' }).getByRole('textbox').fill('J0001-S1')
  await page.getByRole('button', { name: '确定', exact: true }).click()
  await expect(rootRows).toHaveCount(1)
  await expect(page.locator('.el-loading-mask')).toHaveCount(0)
  await page.screenshot({ path: '../Docs/screenshots/03-planning.png', fullPage: true })
  await page.getByRole('button', { name: '确认生成生产单' }).click()
  await page.getByRole('button', { name: '确定', exact: true }).click()
  await page.locator('nav').getByRole('button', { name: '生产执行' }).click()
  const childRow = page.getByRole('row').filter({ hasText: '临时半成品' })
  await childRow.getByRole('button', { name: '开始生产', exact: true }).click()
  await childRow.getByRole('button', { name: '调进度', exact: true }).click()
  await page.getByRole('dialog', { name: '更新自身进度' }).getByRole('textbox').fill('60')
  await page.getByRole('button', { name: '确定', exact: true }).click()
  await page
    .getByRole('dialog', { name: '确认进度反馈' })
    .getByRole('button', { name: '确定', exact: true })
    .click()
  await expect(page.getByRole('dialog', { name: '生产批次详情' })).toBeVisible()
  await page
    .getByRole('dialog', { name: '生产批次详情' })
    .getByRole('button', { name: '关闭此对话框' })
    .click()
  await expect(page.getByRole('dialog', { name: '生产批次详情' })).toBeHidden()
  const parentRow = page.getByRole('row').filter({ hasText: '临时成品' })
  await expect(parentRow).toContainText('36.00%')
  await parentRow.getByRole('button', { name: '详情', exact: true }).click()
  await expect(page.getByRole('button', { name: '开始生产', exact: true })).toBeDisabled()
  await expect(page.locator('.el-loading-mask')).toHaveCount(0)
  await expect
    .poll(async () =>
      page.locator('.el-drawer').evaluate((e) => Math.round(e.getBoundingClientRect().right)),
    )
    .toBe(1366)
  await page.screenshot({ path: '../Docs/screenshots/04-dependency-progress.png', fullPage: true })
  await expect(page.getByRole('dialog', { name: '生产批次详情' })).toBeVisible()
  await page
    .getByRole('dialog', { name: '生产批次详情' })
    .getByRole('button', { name: '关闭此对话框' })
    .click()
  await expect(page.getByRole('dialog', { name: '生产批次详情' })).toBeHidden()
  await childRow.getByRole('button', { name: '调进度', exact: true }).click()
  await page.getByRole('dialog', { name: '更新自身进度' }).getByRole('textbox').fill('100')
  await page.getByRole('button', { name: '确定', exact: true }).click()
  await page
    .getByRole('dialog', { name: '确认进度反馈' })
    .getByRole('button', { name: '确定', exact: true })
    .click()
  await expect(page.getByRole('dialog', { name: '生产批次详情' })).toBeVisible()
  await page
    .getByRole('dialog', { name: '生产批次详情' })
    .getByRole('button', { name: '关闭此对话框' })
    .click()
  await expect(page.getByRole('dialog', { name: '生产批次详情' })).toBeHidden()
  await expect(parentRow).toContainText('可以生产')
  await parentRow.getByRole('button', { name: '开始生产', exact: true }).click()
  await parentRow.getByRole('button', { name: '调进度', exact: true }).click()
  await page.getByRole('dialog', { name: '更新自身进度' }).getByRole('textbox').fill('100')
  await page.getByRole('button', { name: '确定', exact: true }).click()
  await page
    .getByRole('dialog', { name: '确认进度反馈' })
    .getByRole('button', { name: '确定', exact: true })
    .click()
  await expect(page.getByRole('dialog', { name: '生产批次详情' })).toBeVisible()
  await page
    .getByRole('dialog', { name: '生产批次详情' })
    .getByRole('button', { name: '关闭此对话框' })
    .click()
  await expect(page.getByRole('dialog', { name: '生产批次详情' })).toBeHidden()
  await page.locator('nav').getByRole('button', { name: '销售订单' }).click()
  await expect(salesRow).toContainText('生产完成')
  await salesRow.getByRole('button', { name: '详情', exact: true }).click()
  await page.getByRole('button', { name: '追溯涉及的批次' }).click()
  await expect(page.getByRole('heading', { name: '批次依赖图', exact: false })).toBeVisible()
  await expect(page.locator('.vue-flow__node')).toHaveCount(2)
  await expect(page.locator('.el-loading-mask')).toHaveCount(0)
  await page.screenshot({ path: '../Docs/screenshots/05-batch-trace.png', fullPage: true })
  await expect(page.locator('.el-message--error')).toHaveCount(0)
  // Cancellation of a started shared plan preserves completed quantity and batch identity.
  const cancelled = await write('sales-orders', {
    number: 'TEMP-CANCEL',
    customer_name: '临时取消客户',
    default_priority: 'LOW',
    lines: [{ item_id: finished.id, quantity: '40' }],
  })
  await write(`sales-orders/${cancelled.id}/confirm`, { expected_version: cancelled.version })
  const keep = await write('sales-orders', {
    number: 'TEMP-KEEP',
    customer_name: '临时保留客户',
    default_priority: 'LOW',
    lines: [{ item_id: finished.id, quantity: '60' }],
  })
  await write(`sales-orders/${keep.id}/confirm`, { expected_version: keep.version })
  const current = (await (await request.get('/api/v1/plans/current')).json()).data
  await write(`plans/${current.id}/confirm`, { expected_version: current.version })
  const created = (
    await (await request.get(`/api/v1/production-orders?plan_id=${current.id}`)).json()
  ).data.results
  let supplying = created.find((o: { item_id: number }) => o.item_id === semi.id)
  await write(`production-orders/${supplying.id}/start`, { expected_version: supplying.version })
  supplying = (await (await request.get(`/api/v1/production-orders/${supplying.id}`)).json()).data
  await write(`production-orders/${supplying.id}/progress`, {
    expected_version: supplying.version,
    own_progress: '100',
  })
  await page.goto('/#sales-orders')
  const cancelRow = page.getByRole('row').filter({ hasText: 'TEMP-CANCEL' })
  await cancelRow.getByRole('button', { name: '取消', exact: true }).click()
  const impact = page.getByRole('dialog', { name: '确认影响范围' })
  await expect(impact).toContainText('100→60')
  await expect(impact).toContainText('共享批次保留')
  await impact.getByRole('textbox').fill('浏览器取消共享订单验证')
  await impact.getByRole('button', { name: '确定', exact: true }).click()
  await expect(impact).toBeHidden()
  await expect(page.locator('.el-loading-mask')).toHaveCount(0)
  await expect(cancelRow).toContainText('已取消')
  await expect(page.getByRole('row').filter({ hasText: 'TEMP-KEEP' })).toContainText('生产完成')
  const retained = (
    await (await request.get(`/api/v1/production-orders?plan_id=${current.id}`)).json()
  ).data.results
  expect(retained.every((o: { status: string }) => o.status === 'COMPLETED')).toBeTruthy()
  expect(retained.find((o: { item_id: number }) => o.item_id === finished.id).quantity).toBe('60')
  await page.screenshot({ path: '../Docs/screenshots/06-shared-cancellation.png', fullPage: true })
  expect(errors).toEqual([])
})
