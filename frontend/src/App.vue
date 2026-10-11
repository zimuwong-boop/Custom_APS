<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
const GraphView = defineAsyncComponent(() => import('./GraphView.vue'))
import { api, bootstrap, labels, session } from './api'

type Row = Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any
const sections = [
  { id: 'dashboard', name: '工作总览', icon: '◈' },
  { id: 'items', name: '物料档案', icon: '◇' },
  { id: 'boms', name: 'BOM 结构', icon: '⌘' },
  { id: 'sales-orders', name: '销售订单', icon: '▤' },
  { id: 'planning', name: '排产工作台', icon: '⊞' },
  { id: 'production-orders', name: '生产执行', icon: '▷' },
  { id: 'trace', name: '批次追溯', icon: '⌁' },
  { id: 'audit-events', name: '操作记录', icon: '↺' },
]
const section = ref(location.hash.slice(1) || 'dashboard')
const title = computed(() => sections.find((s) => s.id === section.value)?.name || '工作总览')
const rows = ref<Row[]>([]),
  items = ref<Row[]>([]),
  boms = ref<Row[]>([]),
  units = ref<Row[]>([]),
  sales = ref<Row[]>([]),
  production = ref<Row[]>([]),
  demands = ref<Row[]>([])
const plan = ref<Row | null>(null),
  selected = ref<Row | null>(null),
  graph = ref<Row | null>(null)
const search = ref(''),
  statusFilter = ref(''),
  dialog = ref(false),
  form = ref<Row>({}),
  editing = ref<Row | null>(null),
  traceInput = ref(''),
  traceHistory = ref(false)
const page = ref(1),
  total = ref(0),
  busy = ref(false)
function unitName(code?: string) {
  return units.value.find((u) => u.code === code)?.name || code || ''
}
function jobUnit(key: string) {
  const j = plan.value?.graph.jobs.find((j: Row) => j.key === key)
  return unitName(items.value.find((i) => i.id === j?.item_id)?.unit)
}
const statusType = (status: string) =>
  ['COMPLETED', 'PRODUCTION_COMPLETED', 'ACTIVE', 'READY'].includes(status)
    ? 'success'
    : ['REVOKED', 'CANCELLED', 'RETIRED'].includes(status)
      ? 'info'
      : status === 'WAITING'
        ? 'warning'
        : 'primary'
const overview = computed(() => [
  {
    label: '销售订单',
    value: sales.value.length,
    hint: `${sales.value.filter((s) => s.status === 'CONFIRMED').length} 单等待生产`,
  },
  { label: '待排产需求', value: demands.value.length, hint: '已确认 · 尚未完全分配' },
  {
    label: '可以开始生产',
    value: production.value.filter((p) => p.status === 'READY').length,
    hint: '子单依赖已满足',
  },
  {
    label: '生产中的批次',
    value: production.value.filter((p) => p.status === 'IN_PROGRESS').length,
    hint: '由人工更新自身进度',
  },
])
async function run(work: () => Promise<void>) {
  busy.value = true
  try {
    await work()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    busy.value = false
  }
}
async function allRows(resource: string) {
  const first = await api<Row>(`${resource}?page_size=500`)
  const result: Row[] = first.results
  for (let page = 2; result.length < first.total; page++) {
    const data = await api<Row>(`${resource}?page_size=500&page=${page}`)
    if (!data.results.length) break
    result.push(...data.results)
  }
  return { results: result }
}
const statuses = computed(() =>
  section.value === 'boms'
    ? ['DRAFT', 'ACTIVE', 'RETIRED']
    : section.value === 'sales-orders'
      ? ['DRAFT', 'CONFIRMED', 'PRODUCTION_COMPLETED', 'CANCELLED']
      : section.value === 'production-orders'
        ? ['WAITING', 'READY', 'IN_PROGRESS', 'COMPLETED', 'REVOKED']
        : [],
)
async function loadReferences() {
  const result: Row[] = await Promise.all([
    allRows('items'),
    allRows('boms'),
    api<Row>('units'),
    allRows('sales-orders'),
    allRows('production-orders'),
    api<Row[]>('planning/demands'),
  ])
  items.value = result[0]!.results
  boms.value = result[1]!.results
  units.value = result[2]!.results
  sales.value = result[3]!.results
  production.value = result[4]!.results
  demands.value = result[5] as Row[]
}
function queryRows() {
  page.value = 1
  void run(refresh)
}
async function refresh() {
  await bootstrap()
  await loadReferences()
  if (section.value === 'planning') {
    plan.value = await api<Row | null>('plans/current')

    return
  }
  if (['dashboard', 'trace'].includes(section.value)) return
  const data = await api<Row>(
    `${section.value}?page=${page.value}&page_size=50&search=${encodeURIComponent(search.value)}${statusFilter.value ? '&status=' + statusFilter.value : ''}`,
  )
  rows.value = data.results
  total.value = data.total
}
function navigate(id: string) {
  selected.value = null
  rows.value = []
  section.value = id
  location.hash = id
  selected.value = null
  graph.value = null
  page.value = 1
  search.value = ''
  statusFilter.value = ''
  void run(refresh)
}
function newForm(row?: Row) {
  void run(async () => {
    editing.value = row ? await api<Row>(`${section.value}/${row.id}`) : null
    form.value = editing.value
      ? JSON.parse(JSON.stringify(editing.value))
      : section.value === 'items'
        ? { code: '', name: '', type: 'SEMI', unit_id: units.value[0]?.id, active: true }
        : section.value === 'boms'
          ? { item_id: null, revision: 'V1', base_quantity: '1', description: '', lines: [] }
          : { number: '', customer_name: '', default_priority: 'NORMAL', notes: '', lines: [] }
    dialog.value = true
  })
}
function addLine() {
  form.value.lines.push(
    section.value === 'boms'
      ? { component_item_id: null, child_bom_id: null, quantity: '1' }
      : { item_id: null, bom_id: null, quantity: '1', priority_override: null },
  )
}
function availableBoms(itemId: number) {
  return boms.value.filter((b) => b.item_id === itemId && ['ACTIVE', 'RETIRED'].includes(b.status))
}
async function saveForm() {
  await run(async () => {
    const f = form.value
    const body =
      section.value === 'items'
        ? { code: f.code, name: f.name, type: f.type, unit_id: f.unit_id, active: f.active }
        : section.value === 'boms'
          ? {
              item_id: f.item_id,
              revision: f.revision,
              base_quantity: f.base_quantity,
              description: f.description,
              lines: f.lines.map((l: Row) => ({
                component_item_id: l.component_item_id,
                child_bom_id: l.child_bom_id || null,
                quantity: l.quantity,
              })),
            }
          : {
              number: f.number,
              customer_name: f.customer_name,
              default_priority: f.default_priority,
              notes: f.notes,
              lines: f.lines.map((l: Row) => ({
                item_id: l.item_id,
                bom_id: l.bom_id || null,
                quantity: l.quantity,
                priority_override: l.priority_override || null,
              })),
            }
    await api(
      `${section.value}${editing.value ? '/' + editing.value.id : ''}`,
      editing.value ? 'PATCH' : 'POST',
      { ...body, ...(editing.value ? { expected_version: editing.value.version } : {}) },
    )
    dialog.value = false
    ElMessage.success('已保存')
    await refresh()
  })
}
async function detail(row: Row) {
  await run(async () => {
    selected.value = await api<Row>(`${section.value}/${row.id}`)
  })
}
async function act(row: Row, action: string, extra: Row = {}) {
  await run(async () => {
    await api(`${section.value}/${row.id}/${action}`, 'POST', {
      expected_version: row.version,
      ...extra,
    })
    await refresh()
    if (selected.value?.id === row.id) selected.value = await api<Row>(`${section.value}/${row.id}`)
    ElMessage.success('操作已完成')
  })
}
async function remove(row: Row) {
  await run(async () => {
    await ElMessageBox.confirm('删除此草稿？已被引用的记录无法删除。', '删除确认', {
      type: 'warning',
    })
    await api(`${section.value}/${row.id}`, 'DELETE', { expected_version: row.version })
    await refresh()
  })
}
async function reasonAction(row: Row, action: string) {
  await run(async () => {
    const { value } = await ElMessageBox.prompt('请输入操作原因', '填写原因', {
      inputPattern: /\S+/,
      inputErrorMessage: '原因不能为空',
    })
    await api(`${section.value}/${row.id}/${action}`, 'POST', {
      expected_version: row.version,
      reason: value,
    })
    await refresh()
  })
}
async function clone(row: Row) {
  await run(async () => {
    const { value } = await ElMessageBox.prompt('填写新版本号', '复制 BOM')
    await api(`boms/${row.id}/clone`, 'POST', {
      expected_version: row.version,
      new_revision: value,
    })
    await refresh()
  })
}
async function destructive(resource: string, row: Row, action: string) {
  await run(async () => {
    const preview = await api<Row>(`${resource}/${row.id}/${action}-preview`, 'POST', {
      expected_version: row.version,
    })
    const { value } = await ElMessageBox.prompt(
      action === 'cancel'
        ? `将取消该销售单，扣除已分配数量，重算相关子单需求；共享批次保留，已完成量按剩余计划重算进度。涉及 ${preview.quantity_changes.length} 张生产单：${preview.quantity_changes.map((o: Row) => `${o.batch_number}：${o.old_quantity}→${o.new_quantity}`).join('；')}。请填写原因。`
        : `将撤销 ${preview.plan_ids.length} 个排产批次，影响 ${preview.production_order_ids.length} 张生产单、${preview.sales_order_ids.length} 张销售单。请填写原因。`,
      '确认影响范围',
      { inputPattern: /\S+/, inputErrorMessage: '原因不能为空', type: 'warning' },
    )
    await api(`${resource}/${row.id}/${action}`, 'POST', {
      expected_version: row.version,
      confirmation_token: preview.confirmation_token,
      confirm: true,
      reason: value,
    })
    selected.value = null
    await refresh()
  })
}
async function setProgress(row: Row, correction = false) {
  await run(async () => {
    row = await api<Row>(`production-orders/${row.id}`)
    const { value } = await ElMessageBox.prompt(
      `当前自身进度 ${row.own_progress}%，汇总进度 ${row.progress}%。填写新的自身进度（0–100）。`,
      correction ? '纠正自身进度' : '更新自身进度',
      {
        inputValue: String(row.own_progress),
        inputPattern: /^(100(?:\.0{1,2})?|\d{1,2}(?:\.\d{1,2})?)$/,
        inputErrorMessage: '请输入 0–100，最多两位小数',
      },
    )
    const w = row.child_weight === null ? 0 : Number(row.child_weight) / 100
    const previewTotal = w * childAverage(row) + (1 - w) * Number(value)
    await ElMessageBox.confirm(
      `本级自身进度将设为 ${value}%，汇总进度约为 ${previewTotal.toFixed(2)}%。最终结果由系统精确计算。`,
      '确认进度反馈',
    )
    let reason = ''
    if (correction)
      reason = (
        await ElMessageBox.prompt('填写降低进度的原因', '纠错说明', {
          inputPattern: /\S+/,
          inputErrorMessage: '原因不能为空',
        })
      ).value
    await api(
      `production-orders/${row.id}/${correction ? 'correct-progress' : 'progress'}`,
      'POST',
      { expected_version: row.version, own_progress: value, reason },
    )
    await refresh()
    selected.value = await api<Row>(`production-orders/${row.id}`)
  })
}
async function replan() {
  await run(async () => {
    if (plan.value)
      await ElMessageBox.confirm('重新计算将替换当前草稿中的人工调整。', '重新计算排产')
    plan.value = await api<Row | null>('plans/recalculate', 'POST', {
      expected_data_revision: session.revision,
    })

    ElMessage.success(plan.value ? '排产建议已更新' : '目前没有待排产需求')
  })
}
function allocationLabel(lineId: number) {
  const sale = sales.value.find((s) => s.lines.some((l: Row) => l.id === lineId))
  const line = sale?.lines.find((l: Row) => l.id === lineId)
  return sale ? `${sale.number} · ${line.item.name}` : String(lineId)
}
async function adjustment(operation: Row) {
  if (!plan.value) return
  plan.value = await api<Row>(`plans/${plan.value.id}/adjust`, 'POST', {
    expected_version: plan.value.version,
    operation,
  })
  ElMessage.success('已校验并重新计算各层级用量')
}
async function splitJob(row: Row) {
  await run(async () => {
    const { value } = await ElMessageBox.prompt(
      `当前数量 ${row.quantity}。用逗号分隔各份数量，总和必须等于原数量。销售来源和下级用量将自动重新分配。`,
      '拆分生产单',
      { inputPlaceholder: '例如：2,3' },
    )
    await adjustment({
      type: 'split',
      job_key: row.key,
      quantities: value.split(/[,，]/).map((q) => q.trim()),
    })
  })
}
async function mergeJob(row: Row) {
  await run(async () => {
    const compatible = plan.value!.graph.jobs.filter(
      (j: Row) =>
        j.key !== row.key &&
        j.item_id === row.item_id &&
        j.bom_id === row.bom_id &&
        j.priority === row.priority,
    )
    if (!compatible.length) {
      ElMessage.info('没有同物料、同 BOM 版本、同优先级的合并候选')
      return
    }
    const { value } = await ElMessageBox.prompt(
      `可合并节点：${compatible.map((j: Row) => j.key + '（' + j.quantity + '）').join('、')}。输入一个或多个节点，用逗号分隔；合并后沿用当前节点的子单贡献比例。`,
      '合并生产单',
    )
    const keys = value.split(/[,，]/).map((q) => q.trim())
    if (!keys.every((k) => compatible.some((j: Row) => j.key === k)))
      throw new Error('请选择列表中兼容的节点')
    await adjustment({ type: 'merge', job_keys: [row.key, ...keys] })
  })
}
async function weightJob(row: Row) {
  await run(async () => {
    const { value } = await ElMessageBox.prompt(
      '子单全部完成时，本单总进度达到多少？0–100%，不影响所有子单完成前的开工限制。',
      '设置子单贡献比例',
      { inputValue: row.child_weight },
    )
    await adjustment({ type: 'weight', job_key: row.key, child_weight: value })
  })
}
const allocationDialog = ref(false),
  allocationGraph = ref<Row>({ jobs: [], dependencies: [], sales_allocations: [] })
function editAllocation() {
  allocationGraph.value = JSON.parse(JSON.stringify(plan.value!.graph))
  allocationDialog.value = true
}
function jobLabel(key: string) {
  const job = allocationGraph.value.jobs.find((j: Row) => j.key === key)
  return job
    ? `${key} · ${items.value.find((i) => i.id === job.item_id)?.name} · ${job.quantity}`
    : key
}
function outgoingQuantity(job: Row) {
  const graph = allocationGraph.value
  return [
    ...graph.dependencies.filter((e: Row) => e.supplier_key === job.key),
    ...graph.sales_allocations.filter((a: Row) => a.job_key === job.key),
  ].reduce((sum, a) => sum + Number(a.quantity), Number(job.rounding_surplus))
}
async function saveAllocations() {
  await run(async () => {
    plan.value = await api<Row>(`plans/${plan.value!.id}/graph`, 'PUT', {
      expected_version: plan.value!.version,
      graph: allocationGraph.value,
    })
    allocationDialog.value = false
    ElMessage.success('来源分配已保存')
  })
}
function editDependency() {
  editAllocation()
}
const bomGraph = ref<Row | null>(null)
async function showBOMGraph(row: Row) {
  await run(async () => {
    bomGraph.value = await api<Row>(`boms/${row.id}/graph`)
    selected.value = null
  })
}
function childAverage(row: Row) {
  return row.dependencies?.length
    ? row.dependencies.reduce((sum: number, d: Row) => sum + Number(d.progress), 0) /
        row.dependencies.length
    : 0
}
function traceFromSale(id: number) {
  navigate('trace')
  void findTrace(id)
}
async function confirmPlan() {
  await run(async () => {
    if (!plan.value) return
    await ElMessageBox.confirm(
      '确认后将生成各层级独立批次，并冻结数量、依赖和贡献比例。',
      '确认正式排产',
    )
    await api(`plans/${plan.value.id}/confirm`, 'POST', { expected_version: plan.value.version })
    await refresh()
    ElMessage.success('生产单与批次已生成')
  })
}
async function showGraph(row: Row) {
  await run(async () => {
    graph.value = await api<Row>(`production-orders/${row.id}/graph`)
  })
}
async function findTrace(saleId?: number) {
  await run(async () => {
    graph.value = await api<Row>(
      saleId
        ? `trace/sales-orders/${saleId}?include_history=${traceHistory.value}`
        : `trace/batches/${encodeURIComponent(traceInput.value.trim())}`,
    )
  })
}
async function reset() {
  await run(async () => {
    const preview = await api<Row>('demo/reset-preview', 'POST', { scenario_code: null })
    await ElMessageBox.confirm(
      `清空全部业务数据与历史记录：${JSON.stringify(preview.counts)}。批次流水号继续保留。`,
      '重置为空数据',
      { type: 'warning', confirmButtonText: '确认清空' },
    )
    await api('demo/reset', 'POST', {
      scenario_code: null,
      confirm: true,
      confirmation_token: preview.confirmation_token,
    })
    selected.value = null
    graph.value = null
    await refresh()
    ElMessage.success('已重置，业务数据为空')
  })
}
onMounted(() => {
  void run(refresh)
  window.addEventListener('hashchange', () => {
    const id = location.hash.slice(1)
    if (id !== section.value && sections.some((s) => s.id === id)) navigate(id)
  })
  window.addEventListener('focus', () => {
    if (!dialog.value && !allocationDialog.value && !busy.value)
      void run(async () => {
        await refresh()
        if (selected.value && !['planning', 'trace', 'dashboard'].includes(section.value))
          selected.value = await api<Row>(`${section.value}/${selected.value.id}`)
      })
  })
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-mark">A</span>
        <div>Custom APS<small>生产协同演示系统</small></div>
      </div>
      <div class="nav-label">工作空间</div>
      <nav>
        <button
          v-for="s in sections"
          :key="s.id"
          :class="{ active: section === s.id }"
          @click="navigate(s.id)"
        >
          <span>{{ s.icon }}</span
          >{{ s.name }}
        </button>
      </nav>
      <div class="sidebar-footer">
        <span class="live-dot"></span> 单实例 · SQLite<small>无库存 / 无产能约束</small>
      </div>
    </aside>
    <main v-loading="busy" class="workspace">
      <header>
        <div>
          <div class="eyebrow">CUSTOM APS / WORKSPACE</div>
          <h1>{{ title }}</h1>
        </div>
        <div class="header-actions">
          <span class="epoch">数据版本 {{ session.epoch }}</span
          ><el-button @click="run(refresh)">刷新</el-button
          ><el-button
            v-if="['items', 'boms', 'sales-orders'].includes(section)"
            type="primary"
            @click="newForm()"
            >＋ 新建{{
              section === 'items' ? '物料' : section === 'boms' ? 'BOM' : '销售单'
            }}</el-button
          >
        </div>
      </header>
      <template v-if="section === 'dashboard'">
        <div class="intro">
          <div>
            <span class="pill">需求 → 排产 → 执行 → 追溯</span>
            <h2>每一层生产，都有来处与去向。</h2>
            <p>
              从确认销售需求开始，自动展开 BOM
              并生成排产建议。人工调整和执行，进度逐层反馈至销售单。
            </p>
            <el-button type="primary" @click="navigate('sales-orders')">进入销售订单</el-button
            ><el-button @click="navigate('planning')">查看排产建议 →</el-button>
          </div>
          <div class="intro-art">
            <span>销售需求</span><i>↓</i><span>成品批次</span><i>↓</i>
            <div><span>半成品</span><span>原料需求</span></div>
          </div>
        </div>
        <div class="metric-grid">
          <div v-for="m in overview" :key="m.label" class="metric">
            <span>{{ m.label }}</span
            ><strong>{{ m.value }}</strong
            ><small>{{ m.hint }}</small>
          </div>
        </div>
        <div class="two-columns">
          <section class="panel">
            <div class="panel-title">
              <h3>生产执行</h3>
              <el-button text @click="navigate('production-orders')">全部批次 →</el-button>
            </div>
            <el-empty
              v-if="!production.length"
              description="暂无生产批次，确认排产后将在这里显示"
            />
            <div
              v-for="o in production.filter((p) => p.status !== 'REVOKED').slice(0, 5)"
              :key="o.id"
              class="activity-row"
            >
              <div>
                <strong>{{ o.item.name }}</strong
                ><small>{{ o.batch_number }}</small>
              </div>
              <el-tag :type="statusType(o.status)">{{ labels[o.status] }}</el-tag
              ><b>{{ o.progress }}%</b>
            </div>
          </section>
          <section class="panel">
            <h3>从空白开始</h3>
            <ol class="steps">
              <li>
                <b>建立物料与 BOM</b>
                <p>从原料开始，逐层建立半成品和成品，生效明确的 BOM 版本。</p>
              </li>
              <li>
                <b>确认销售单</b>
                <p>自动拆分需求，相同产品、版本和优先级给出合并建议。</p>
              </li>
              <li>
                <b>确认排产并推进生产</b>
                <p>先完成底层子单，再执行父单；销售进度实时反馈。</p>
              </li>
            </ol>
            <div class="subtle">正式演示数据待开发完成后规划，当前不预置业务数据。</div>
          </section>
        </div>
      </template>
      <template v-else-if="section === 'planning'">
        <div class="notice">
          同物料、同 BOM 版本、同优先级合并。原料仅计算需求；每个成品和半成品层级均有生产单。
        </div>
        <section class="panel">
          <div class="panel-title">
            <h3>
              待排产需求 <span class="count">{{ demands.length }}</span>
            </h3>
            <el-button @click="replan">重新计算建议</el-button>
          </div>
          <el-table :data="demands"
            ><el-table-column prop="sales_order_number" label="销售单" /><el-table-column
              label="物料"
              ><template #default="{ row }"
                >{{ row.item.code }} · {{ row.item.name }}</template
              ></el-table-column
            ><el-table-column label="未分配数量"
              ><template #default="{ row }"
                >{{ row.pending_quantity }} {{ unitName(row.item.unit) }}</template
              ></el-table-column
            ><el-table-column label="优先级"
              ><template #default="{ row }">{{ labels[row.priority] }}</template></el-table-column
            ></el-table
          >
        </section>
        <section v-if="plan" class="panel">
          <div class="panel-title">
            <div>
              <h3>排产建议 {{ plan.number }}</h3>
              <small>草稿版本 {{ plan.version }} · 共 {{ plan.graph.jobs.length }} 张生产单</small>
            </div>
            <el-button type="primary" @click="confirmPlan">确认生成生产单</el-button>
          </div>
          <el-table :data="plan.graph.jobs">
            <el-table-column prop="key" label="生产节点" width="130" />
            <el-table-column label="物料 / BOM"
              ><template #default="{ row }"
                >{{ items.find((i) => i.id === row.item_id)?.name }} /
                {{ boms.find((b) => b.id === row.bom_id)?.revision }}</template
              ></el-table-column
            >
            <el-table-column label="生产数量" width="120"
              ><template #default="{ row }"
                >{{ row.quantity }} {{ jobUnit(row.key) }}</template
              ></el-table-column
            >
            <el-table-column label="优先级" width="80"
              ><template #default="{ row }">{{ labels[row.priority] }}</template></el-table-column
            >
            <el-table-column label="子单贡献" width="130"
              ><template #default="{ row }">{{
                row.child_weight === null ? '底层子单' : row.child_weight + '%'
              }}</template></el-table-column
            >
            <el-table-column label="调整" width="240"
              ><template #default="{ row }"
                ><el-button link type="primary" @click="splitJob(row)">拆单</el-button
                ><el-button link @click="mergeJob(row)">合单</el-button
                ><el-button v-if="row.child_weight !== null" link @click="weightJob(row)"
                  >设置贡献</el-button
                ></template
              ></el-table-column
            >
          </el-table>
          <div v-if="plan.validation?.quantity_changes?.length" class="notice mt">
            <b>拆分 / 合并后重新展开的用量差异</b>
            <p v-for="change in plan.validation.quantity_changes" :key="change.item_id">
              {{ items.find((i) => i.id === change.item_id)?.name }}：{{ change.old_quantity }} →
              {{ change.new_quantity }}（差额
              {{ change.difference }}）。每张消费单分别取整，系统已重新计算各层级。
            </p>
          </div>
          <h3 class="mt">销售来源分配</h3>
          <el-table :data="plan.graph.sales_allocations"
            ><el-table-column label="销售单 / 商品"
              ><template #default="{ row }">{{
                allocationLabel(row.sales_line_id)
              }}</template></el-table-column
            ><el-table-column prop="job_key" label="对应生产节点" /><el-table-column
              prop="quantity"
              label="分配数量"
            /><el-table-column label="操作" width="120"
              ><template #default
                ><el-button link type="primary" @click="editAllocation()"
                  >调整分配</el-button
                ></template
              ></el-table-column
            ></el-table
          >
          <h3 class="mt">生产供需分配</h3>
          <el-table :data="plan.graph.dependencies"
            ><el-table-column prop="supplier_key" label="供应子单" /><el-table-column
              prop="consumer_key"
              label="消费父单"
            /><el-table-column prop="quantity" label="分配数量" /><el-table-column
              label="操作"
              width="120"
              ><template #default
                ><el-button link type="primary" @click="editDependency()"
                  >调整分配</el-button
                ></template
              ></el-table-column
            ></el-table
          >
        </section>
        <el-empty v-else description="没有待确认的排产建议" />
      </template>
      <template v-else-if="section === 'trace'">
        <section class="panel">
          <h3>追溯产品涉及的所有生产批次</h3>
          <p class="muted">
            支持共享子批次、直接销售半成品和跨销售单合并生产。依赖边显示实际分配数量。
          </p>
          <div class="toolbar">
            <el-input
              v-model="traceInput"
              placeholder="输入完整批次号"
              clearable
              style="width: 400px"
              @keyup.enter="findTrace()"
            /><el-button type="primary" :disabled="!traceInput.trim()" @click="findTrace()"
              >按批次追溯</el-button
            ><el-select placeholder="或选择销售单" style="width: 240px" @change="findTrace"
              ><el-option
                v-for="s in sales"
                :key="s.id"
                :label="s.number + ' · ' + s.customer_name"
                :value="s.id" /></el-select
            ><el-checkbox v-model="traceHistory">包含撤销历史</el-checkbox>
          </div>
        </section>
      </template>
      <template v-else>
        <section class="panel">
          <div class="toolbar">
            <el-input
              v-model="search"
              placeholder="搜索编码、名称或单号"
              clearable
              style="width: 320px"
              @keyup.enter="run(refresh)"
            /><el-button @click="queryRows()">查询</el-button
            ><el-select
              v-if="statuses.length"
              v-model="statusFilter"
              placeholder="筛选状态"
              clearable
              style="width: 160px"
              @change="queryRows"
              ><el-option v-for="s in statuses" :key="s" :value="s" :label="labels[s]" /></el-select
            ><span class="muted">共 {{ total }} 条记录</span>
          </div>
          <el-table :key="section" :data="rows" empty-text="暂无记录" stripe>
            <template v-if="section === 'items'"
              ><el-table-column prop="code" label="物料编码" /><el-table-column
                prop="name"
                label="名称"
              /><el-table-column label="类型"
                ><template #default="{ row }"
                  ><el-tag :type="row.type === 'RAW' ? 'info' : 'primary'">{{
                    labels[row.type]
                  }}</el-tag></template
                ></el-table-column
              ><el-table-column prop="unit" label="单位" /><el-table-column label="启用"
                ><template #default="{ row }">{{
                  row.active ? '是' : '否'
                }}</template></el-table-column
              ></template
            >
            <template v-else-if="section === 'boms'"
              ><el-table-column label="物料"
                ><template #default="{ row }"
                  >{{ row.item.code }} · {{ row.item.name }}</template
                ></el-table-column
              ><el-table-column prop="revision" label="BOM 版本" /><el-table-column
                prop="base_quantity"
                label="基准产量"
            /></template>
            <template v-else-if="section === 'sales-orders'"
              ><el-table-column prop="number" label="销售单号" /><el-table-column
                prop="customer_name"
                label="客户" /><el-table-column label="优先级"
                ><template #default="{ row }">{{
                  labels[row.default_priority]
                }}</template></el-table-column
              ><el-table-column label="生产进度" width="180"
                ><template #default="{ row }"
                  ><el-progress
                    :percentage="Number(row.progress)"
                    :stroke-width="7" /></template></el-table-column
            ></template>
            <template v-else-if="section === 'production-orders'"
              ><el-table-column
                prop="batch_number"
                label="独立批次 / 生产单"
                min-width="280"
              /><el-table-column label="物料"
                ><template #default="{ row }">{{ row.item.name }}</template></el-table-column
              ><el-table-column label="数量" width="100"
                ><template #default="{ row }"
                  >{{ row.quantity }} {{ unitName(row.item.unit) }}</template
                ></el-table-column
              ><el-table-column label="层级" width="80"
                ><template #default="{ row }">L{{ row.level }}</template></el-table-column
              ><el-table-column label="自身 / 汇总" width="140"
                ><template #default="{ row }"
                  >{{ row.own_progress }} / <b>{{ row.progress }}%</b></template
                ></el-table-column
              ></template
            >
            <template v-else-if="section === 'audit-events'"
              ><el-table-column prop="event_type" label="操作" /><el-table-column
                prop="entity_id"
                label="记录 ID"
                width="100"
              /><el-table-column prop="reason" label="原因" /><el-table-column label="时间"
                ><template #default="{ row }">{{
                  new Date(row.created_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
                }}</template></el-table-column
              ></template
            >
            <el-table-column
              v-if="section !== 'items' && section !== 'audit-events'"
              label="状态"
              width="130"
              ><template #default="{ row }"
                ><el-tag :type="statusType(row.status)">{{ labels[row.status] }}</el-tag></template
              ></el-table-column
            >
            <el-table-column
              label="操作"
              :width="section === 'production-orders' ? 220 : 280"
              fixed="right"
              ><template #default="{ row }"
                ><el-button link type="primary" @click="detail(row)">详情</el-button
                ><template
                  v-if="
                    section === 'items' ||
                    (row.status === 'DRAFT' && ['boms', 'sales-orders'].includes(section))
                  "
                  ><el-button link @click="newForm(row)">编辑</el-button
                  ><el-button link type="danger" @click="remove(row)">删除</el-button></template
                ><template v-if="section === 'boms'"
                  ><el-button
                    v-if="row.status === 'DRAFT'"
                    link
                    type="primary"
                    @click="act(row, 'activate')"
                    >生效</el-button
                  ><el-button
                    v-if="row.status === 'ACTIVE'"
                    link
                    @click="reasonAction(row, 'retire')"
                    >停用</el-button
                  ><el-button link @click="clone(row)">复制版本</el-button></template
                ><template v-if="section === 'sales-orders'"
                  ><el-button
                    v-if="row.status === 'DRAFT'"
                    link
                    type="primary"
                    @click="act(row, 'confirm')"
                    >确认需求</el-button
                  ><el-button
                    v-if="['DRAFT', 'CONFIRMED', 'PRODUCTION_COMPLETED'].includes(row.status)"
                    link
                    type="danger"
                    @click="destructive('sales-orders', row, 'cancel')"
                    >取消</el-button
                  ></template
                ><template v-if="section === 'production-orders'"
                  ><el-button v-if="row.can_start" link type="primary" @click="act(row, 'start')"
                    >开始生产</el-button
                  ><el-button
                    v-if="row.can_update_progress"
                    link
                    type="primary"
                    @click="setProgress(row)"
                    >调进度</el-button
                  ></template
                ></template
              ></el-table-column
            > </el-table
          ><el-pagination
            v-if="total > 50"
            v-model:current-page="page"
            :total="total"
            :page-size="50"
            layout="prev, pager, next"
            class="mt"
            @current-change="run(refresh)"
          />
        </section>
        <div v-if="section === 'audit-events'" class="reset-bar">
          <p>重置会清空业务与历史数据，保留单位、系统设置和批次流水号。</p>
          <el-button type="danger" plain @click="reset">重置为空数据</el-button>
        </div>
      </template>
      <section v-if="bomGraph && section === 'boms'" class="panel">
        <div class="panel-title">
          <h3>全部制造层级 · 共享 BOM 只列一次</h3>
          <el-button text @click="bomGraph = null">关闭</el-button>
        </div>
        <div v-for="b in bomGraph.nodes" :key="b.id" class="mt">
          <h3>
            {{ b.item.code }} · {{ b.item.name }} / {{ b.revision }} · 基准产量
            {{ b.base_quantity }}
          </h3>
          <el-table :data="b.lines"
            ><el-table-column label="组成物料"
              ><template #default="{ row }"
                >{{ row.component.code }} · {{ row.component.name }}</template
              ></el-table-column
            ><el-table-column label="类型"
              ><template #default="{ row }">{{
                labels[row.component.type]
              }}</template></el-table-column
            ><el-table-column label="用量"
              ><template #default="{ row }"
                >{{ row.quantity }} {{ unitName(row.component.unit) }}</template
              ></el-table-column
            ><el-table-column label="子 BOM"
              ><template #default="{ row }">{{
                boms.find((b) => b.id === row.child_bom_id)?.revision || '原料叶节点'
              }}</template></el-table-column
            ></el-table
          >
        </div>
      </section>
      <section v-if="graph" class="panel">
        <div class="panel-title">
          <h3>
            批次依赖图 <span class="count">{{ graph.nodes.length }} 个批次</span>
          </h3>
          <el-button text @click="graph = null">关闭</el-button>
        </div>
        <GraphView :graph="graph as any" /><el-table :data="graph.sales_allocations"
          ><el-table-column prop="sales_order_number" label="关联销售单" /><el-table-column
            prop="production_order_id"
            label="生产单 ID"
          /><el-table-column prop="quantity" label="分配数量" /><el-table-column label="完成确认"
            ><template #default="{ row }">{{
              row.fulfilled ? '已完成' : '待完成'
            }}</template></el-table-column
          ></el-table
        >
      </section>
      <footer>Custom APS · 所有时间按上海时区显示 · 进度表示加工状态，不代表可交付数量</footer>
    </main>
    <el-dialog
      v-model="dialog"
      :title="(editing ? '编辑' : '新建') + title"
      width="850px"
      destroy-on-close
      ><el-form label-position="top" @submit.prevent="saveForm">
        <template v-if="section === 'items'"
          ><div class="form-grid">
            <el-form-item label="物料编码"
              ><el-input v-model="form.code" maxlength="60" /></el-form-item
            ><el-form-item label="物料名称"
              ><el-input v-model="form.name" maxlength="120" /></el-form-item
            ><el-form-item label="物料类型"
              ><el-select v-model="form.type"
                ><el-option
                  v-for="t in ['FINISHED', 'SEMI', 'RAW']"
                  :key="t"
                  :label="labels[t]"
                  :value="t" /></el-select></el-form-item
            ><el-form-item label="单位"
              ><el-select v-model="form.unit_id"
                ><el-option
                  v-for="u in units"
                  :key="u.id"
                  :label="u.name + ' / ' + u.code"
                  :value="u.id" /></el-select
            ></el-form-item>
          </div>
          <el-switch v-model="form.active" active-text="启用物料"
        /></template>
        <template v-else-if="section === 'boms'"
          ><div class="form-grid">
            <el-form-item label="所属成品 / 半成品"
              ><el-select v-model="form.item_id" filterable :disabled="!!editing"
                ><el-option
                  v-for="i in items.filter(
                    (i) => i.type !== 'RAW' && i.active && availableBoms(i.id).length > 0,
                  )"
                  :key="i.id"
                  :label="i.code + ' · ' + i.name"
                  :value="i.id" /></el-select></el-form-item
            ><el-form-item label="版本号"><el-input v-model="form.revision" /></el-form-item
            ><el-form-item label="基准产量"><el-input v-model="form.base_quantity" /></el-form-item
            ><el-form-item label="说明"><el-input v-model="form.description" /></el-form-item></div
        ></template>
        <template v-else
          ><div class="form-grid">
            <el-form-item label="销售单号"><el-input v-model="form.number" /></el-form-item
            ><el-form-item label="客户名称"><el-input v-model="form.customer_name" /></el-form-item
            ><el-form-item label="默认优先级"
              ><el-select v-model="form.default_priority"
                ><el-option
                  v-for="p in ['HIGH', 'NORMAL', 'LOW']"
                  :key="p"
                  :label="labels[p]"
                  :value="p" /></el-select></el-form-item
            ><el-form-item label="备注"><el-input v-model="form.notes" /></el-form-item></div
        ></template>
        <template v-if="section !== 'items'"
          ><div class="panel-title">
            <h3>{{ section === 'boms' ? '组成明细' : '销售明细' }}</h3>
            <el-button @click="addLine">＋ 添加行</el-button>
          </div>
          <div v-for="(line, index) in form.lines" :key="index" class="line-form">
            <el-select
              v-if="section === 'boms'"
              v-model="line.component_item_id"
              filterable
              placeholder="选择半成品或原料"
              @change="line.child_bom_id = null"
              ><el-option
                v-for="i in items.filter((i) => i.type !== 'FINISHED' && i.active)"
                :key="i.id"
                :label="i.code + ' · ' + i.name"
                :value="i.id" /></el-select
            ><el-select
              v-else
              v-model="line.item_id"
              filterable
              placeholder="选择有可用 BOM 的销售商品"
              @change="line.bom_id = null"
              ><el-option
                v-for="i in items.filter(
                  (i) => i.type !== 'RAW' && i.active && availableBoms(i.id).length > 0,
                )"
                :key="i.id"
                :label="i.code + ' · ' + i.name"
                :value="i.id" /></el-select
            ><el-input v-model="line.quantity" placeholder="数量" style="width: 110px" /><el-select
              v-if="section === 'boms'"
              v-model="line.child_bom_id"
              placeholder="半成品 BOM 版本"
              clearable
              :disabled="items.find((i) => i.id === line.component_item_id)?.type === 'RAW'"
              ><el-option
                v-for="b in availableBoms(line.component_item_id)"
                :key="b.id"
                :label="b.revision + ' · ' + labels[b.status]"
                :value="b.id" /></el-select
            ><template v-else
              ><el-select v-model="line.bom_id" placeholder="确认时使用生效 BOM" clearable
                ><el-option
                  v-for="b in availableBoms(line.item_id)"
                  :key="b.id"
                  :label="b.revision + ' · ' + labels[b.status]"
                  :value="b.id" /></el-select
              ><el-select
                v-model="line.priority_override"
                placeholder="继承优先级"
                clearable
                style="width: 130px"
                ><el-option
                  v-for="p in ['HIGH', 'NORMAL', 'LOW']"
                  :key="p"
                  :label="labels[p]"
                  :value="p" /></el-select></template
            ><el-button link type="danger" @click="form.lines.splice(index, 1)">删除</el-button>
          </div></template
        > </el-form
      ><template #footer
        ><el-button @click="dialog = false">取消</el-button
        ><el-button type="primary" :loading="busy" @click="saveForm">保存</el-button></template
      ></el-dialog
    >
    <el-dialog v-model="allocationDialog" title="调整销售与供需分配" width="1000px">
      <div class="notice">
        每张生产单的分配数量加声明余量必须等于计划数量；每个父单的 BOM
        用量必须完整覆盖。通过选择节点和修改数量调整来源，不会生成新的销售需求。
      </div>
      <h3>数量守恒检查</h3>
      <div class="toolbar">
        <el-tag
          v-for="job in allocationGraph.jobs"
          :key="job.key"
          :type="
            Math.abs(outgoingQuantity(job) - Number(job.quantity)) < 0.0000001
              ? 'success'
              : 'danger'
          "
          >{{ job.key }}：已分配 {{ outgoingQuantity(job) }} / 计划 {{ job.quantity }}</el-tag
        >
      </div>
      <h3>销售分配</h3>
      <el-table :data="allocationGraph.sales_allocations"
        ><el-table-column label="销售明细"
          ><template #default="{ row }"
            ><el-select v-model="row.sales_line_id" filterable
              ><template v-for="sale in sales" :key="sale.id"
                ><el-option
                  v-for="line in sale.lines"
                  :key="line.id"
                  :value="line.id"
                  :label="
                    sale.number + ' · ' + line.item.name
                  " /></template></el-select></template></el-table-column
        ><el-table-column label="顶层生产单"
          ><template #default="{ row }"
            ><el-select v-model="row.job_key"
              ><el-option
                v-for="j in allocationGraph.jobs"
                :key="j.key"
                :label="jobLabel(j.key)"
                :value="j.key" /></el-select></template></el-table-column
        ><el-table-column label="数量" width="130"
          ><template #default="{ row }"
            ><el-input v-model="row.quantity" /></template></el-table-column
        ><el-table-column width="80"
          ><template #default="{ $index }"
            ><el-button
              link
              type="danger"
              @click="allocationGraph.sales_allocations.splice($index, 1)"
              >删除</el-button
            ></template
          ></el-table-column
        ></el-table
      ><el-button
        class="mt"
        @click="
          allocationGraph.sales_allocations.push({
            sales_line_id: null,
            job_key: null,
            quantity: '1',
          })
        "
        >添加销售分配</el-button
      >
      <h3 class="mt">生产供需分配</h3>
      <el-table :data="allocationGraph.dependencies"
        ><el-table-column label="供应子单"
          ><template #default="{ row }"
            ><el-select v-model="row.supplier_key"
              ><el-option
                v-for="j in allocationGraph.jobs"
                :key="j.key"
                :label="jobLabel(j.key)"
                :value="j.key" /></el-select></template></el-table-column
        ><el-table-column label="消费父单"
          ><template #default="{ row }"
            ><el-select v-model="row.consumer_key"
              ><el-option
                v-for="j in allocationGraph.jobs"
                :key="j.key"
                :label="jobLabel(j.key)"
                :value="j.key" /></el-select></template></el-table-column
        ><el-table-column label="数量" width="130"
          ><template #default="{ row }"
            ><el-input v-model="row.quantity" /></template></el-table-column
        ><el-table-column width="80"
          ><template #default="{ $index }"
            ><el-button link type="danger" @click="allocationGraph.dependencies.splice($index, 1)"
              >删除</el-button
            ></template
          ></el-table-column
        ></el-table
      ><el-button
        class="mt"
        @click="
          allocationGraph.dependencies.push({
            supplier_key: null,
            consumer_key: null,
            quantity: '1',
          })
        "
        >添加供需分配</el-button
      >
      <template #footer
        ><el-button @click="allocationDialog = false">取消</el-button
        ><el-button type="primary" @click="saveAllocations">校验并保存</el-button></template
      >
    </el-dialog>
    <el-drawer
      :model-value="!!selected"
      :title="section === 'production-orders' ? '生产批次详情' : '记录详情'"
      size="680px"
      @close="selected = null"
      ><template v-if="selected"
        ><template v-if="section === 'production-orders'"
          ><h2>{{ selected.item.name }}</h2>
          <p class="mono">{{ selected.batch_number }}</p>
          <p class="muted">
            计划生产 {{ selected.quantity }} {{ unitName(selected.item.unit) }} · BOM
            {{ selected.bom_snapshot.revision }} · 优先级 {{ labels[selected.priority] }}
          </p>
          <div class="detail-metrics">
            <div>
              <small>自身进度</small><strong>{{ selected.own_progress }}%</strong>
            </div>
            <div>
              <small>汇总进度</small><strong>{{ selected.progress }}%</strong>
            </div>
            <div>
              <small>子单贡献</small
              ><strong>{{
                selected.child_weight === null ? '—' : selected.child_weight + '%'
              }}</strong>
            </div>
          </div>
          <div class="toolbar">
            <el-tag :type="statusType(selected.status)">{{ labels[selected.status] }}</el-tag
            ><el-button v-if="selected.can_start" type="primary" @click="act(selected, 'start')"
              >开始生产</el-button
            ><el-button
              v-if="selected.can_update_progress"
              type="primary"
              @click="setProgress(selected)"
              >更新自身进度</el-button
            ><el-button
              v-if="selected.actual_started_at && Number(selected.own_progress) > 0"
              @click="setProgress(selected, true)"
              >纠错</el-button
            ><el-button @click="showGraph(selected)">依赖图</el-button
            ><el-button
              v-if="!selected.actual_started_at && selected.status !== 'REVOKED'"
              @click="
                run(async () => {
                  const p = await api<Row>('plans/' + selected!.plan_id)
                  await destructive('plans', p, 'revoke')
                })
              "
              >撤销整批排产</el-button
            >
          </div>
          <div class="notice">
            <template v-if="selected.child_weight !== null"
              >子单贡献：直接子单平均 {{ childAverage(selected).toFixed(2) }}% ×
              {{ selected.child_weight }}%<br />自身贡献：{{ selected.own_progress }}% ×
              {{ (100 - Number(selected.child_weight)).toFixed(2) }}%</template
            >
            <template v-else>底层生产单，总进度等于本级自身生产进度。</template>
            <p v-if="selected.child_weight === '100.00'">
              本单由子单完成自动完成，无需本级手工加工。
            </p>
            <p v-if="selected.status === 'READY' && selected.child_weight !== null">
              子单已全部完成，本级尚未开始加工；当前进度为子单贡献。
            </p>
          </div>
          <div v-if="selected.status === 'WAITING'" class="notice">
            子单尚未全部完成，当前不能开始生产或修改自身进度。
          </div>
          <div v-if="selected.status === 'WAITING'" class="toolbar">
            <el-button disabled>开始生产</el-button><el-button disabled>更新自身进度</el-button>
          </div>
          <h3>直接生产子单</h3>
          <el-table :data="selected.dependencies"
            ><el-table-column prop="batch_number" label="子批次" min-width="260" /><el-table-column
              prop="quantity"
              label="数量"
            /><el-table-column label="进度"
              ><template #default="{ row }">{{ row.progress }}%</template></el-table-column
            ></el-table
          >
          <p v-if="selected.has_cancellation_credit" class="notice">
            销售取消后保留已完成工作量，当前总进度可能高于常规子单贡献公式；所有子单完成后仍才能开工。
          </p>
          <h3>原料需求</h3>
          <el-table :data="selected.raw_requirements"
            ><el-table-column label="原料"
              ><template #default="{ row }">{{ row.item.name }}</template></el-table-column
            ><el-table-column label="需求数量"
              ><template #default="{ row }"
                >{{ row.quantity }} {{ unitName(row.item.unit) }}</template
              ></el-table-column
            ></el-table
          ></template
        ><template v-else-if="section === 'sales-orders'"
          ><h2>{{ selected.number }}</h2>
          <p>{{ selected.customer_name }} · {{ labels[selected.status] }}</p>
          <el-progress :percentage="Number(selected.progress)" />
          <p class="muted">销售进度按各个不重复的顶层生产批次等权计算，与商品数量无关。</p>
          <div
            v-if="selected.lines.some((l: Row) => Number(l.pending_quantity) > 0)"
            class="notice"
          >
            已安排部分进度 {{ selected.assigned_progress }}%；仍有未安排数量，不能视为整单完成。
          </div>
          <h3>参与等权计算的顶层批次</h3>
          <el-table :data="production.filter((o) => selected!.production_order_ids.includes(o.id))"
            ><el-table-column
              prop="batch_number"
              label="生产批次"
              min-width="280"
            /><el-table-column label="总进度"
              ><template #default="{ row }">{{ row.progress }}%</template></el-table-column
            ></el-table
          >
          <h3>商品与生产覆盖</h3>
          <el-table :data="selected.lines"
            ><el-table-column label="商品"
              ><template #default="{ row }">{{ row.item.name }}</template></el-table-column
            ><el-table-column label="销售量"
              ><template #default="{ row }"
                >{{ row.quantity }} {{ unitName(row.item.unit) }}</template
              ></el-table-column
            ><el-table-column prop="assigned_quantity" label="已排产" /><el-table-column
              prop="pending_quantity"
              label="待排产"
            /><el-table-column label="进度"
              ><template #default="{ row }">{{ row.progress }}%</template></el-table-column
            ></el-table
          ><el-button class="mt" @click="traceFromSale(selected.id)"
            >追溯涉及的批次</el-button
          ></template
        ><template v-else-if="section === 'boms'"
          ><h2>{{ selected.item.name }} · {{ selected.revision }}</h2>
          <p>
            基准产量 {{ selected.base_quantity }} {{ selected.item.unit }} ·
            {{ labels[selected.status] }}
          </p>
          <el-button class="mt" @click="showBOMGraph(selected)">展开所有 BOM 层级</el-button
          ><el-table :data="selected.lines"
            ><el-table-column label="组成"
              ><template #default="{ row }"
                >{{ row.component.code }} · {{ row.component.name }}</template
              ></el-table-column
            ><el-table-column label="用量"
              ><template #default="{ row }"
                >{{ row.quantity }} {{ unitName(row.component.unit) }}</template
              ></el-table-column
            ><el-table-column prop="child_bom_id" label="子 BOM ID" /></el-table
        ></template>
        <template v-else-if="section === 'items'"
          ><h2>{{ selected.name }}</h2>
          <p>{{ selected.code }} · {{ labels[selected.type] }} · {{ selected.unit }}</p>
          <p>物料状态：{{ selected.active ? '启用' : '停用' }}</p>
          <p class="muted">
            引用后的编码、类型和单位不可修改。更改名称不会影响已经生成的批次快照。
          </p></template
        >
        <pre v-else class="json-detail">{{ JSON.stringify(selected, null, 2) }}</pre>
      </template></el-drawer
    >
  </div>
</template>

<style>
:root {
  font-family: Inter, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  color: #223c34;
  background: #f3f6f4;
  font-synthesis: none;
  --el-color-primary: #197557;
  --el-color-success: #239368;
  --el-border-radius-base: 7px;
}
* {
  box-sizing: border-box;
}
body {
  margin: 0;
}
button,
input {
  font: inherit;
}
.app-shell {
  display: flex;
  min-height: 100vh;
}
.sidebar {
  position: fixed;
  width: 232px;
  inset: 0 auto 0 0;
  background: #123c30;
  color: #d5e6de;
  padding: 32px 20px;
  display: flex;
  flex-direction: column;
}
.brand {
  display: flex;
  gap: 12px;
  align-items: center;
  font-weight: 700;
  font-size: 19px;
  letter-spacing: 0.3px;
}
.brand-mark {
  background: #bfe4a7;
  color: #123c30;
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border-radius: 11px;
  font-size: 25px;
}
.brand small {
  display: block;
  font-weight: 400;
  font-size: 11px;
  margin-top: 7px;
  color: #8eb3a3;
}
.nav-label {
  font-size: 10px;
  letter-spacing: 2px;
  color: #83aa99;
  margin: 42px 12px 15px;
}
nav {
  display: grid;
  gap: 7px;
}
nav button {
  border: 0;
  background: transparent;
  color: #b8d0c5;
  text-align: left;
  padding: 14px 14px;
  border-radius: 8px;
  cursor: pointer;
  display: flex;
  gap: 15px;
  align-items: center;
  font-size: 14px;
}
nav button span {
  font-size: 21px;
  width: 20px;
}
nav button:hover {
  background: #204c3e;
}
nav button.active {
  background: #d8eec9;
  color: #123c30;
  font-weight: 600;
}
.sidebar-footer {
  margin-top: auto;
  padding: 25px 12px 0;
  font-size: 12px;
  color: #acc8b8;
  border-top: 1px solid #305546;
}
.sidebar-footer small {
  display: block;
  margin-top: 12px;
  color: #7fa38f;
}
.live-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  background: #b2d895;
  border-radius: 50%;
  margin-right: 8px;
}
.workspace {
  margin-left: 232px;
  width: calc(100% - 232px);
  padding: 36px 42px;
  max-width: 2000px;
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 30px;
}
.eyebrow {
  font-size: 10px;
  letter-spacing: 2px;
  color: #7e9387;
}
h1 {
  font-size: 28px;
  margin: 10px 0 0;
  font-weight: 650;
  letter-spacing: -0.6px;
}
.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
.epoch {
  font-size: 12px;
  color: #7f9287;
  margin-right: 10px;
}
h2 {
  font-size: 27px;
  font-weight: 600;
  line-height: 1.5;
}
h3 {
  font-size: 15px;
  font-weight: 600;
  margin: 0 0 18px;
}
.intro {
  display: flex;
  justify-content: space-between;
  background: #e3eddf;
  border: 1px solid #d7e3d4;
  border-radius: 14px;
  padding: 32px 36px;
  margin-bottom: 24px;
}
.pill {
  font-size: 11px;
  color: #4d765d;
  letter-spacing: 1px;
}
.intro h2 {
  margin: 17px 0 10px;
}
.intro p {
  font-size: 13px;
  color: #6b8070;
  max-width: 620px;
  line-height: 1.9;
  margin-bottom: 22px;
}
.intro-art {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-width: 260px;
  gap: 5px;
}
.intro-art span {
  display: inline-block;
  background: #f7faf3;
  border: 1px solid #c5d8ba;
  padding: 10px 26px;
  border-radius: 7px;
  font-size: 12px;
}
.intro-art i {
  font-style: normal;
  color: #84a375;
}
.intro-art div {
  display: flex;
  gap: 12px;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 18px;
  margin-bottom: 24px;
}
.metric {
  background: #fff;
  border: 1px solid #e2e9e4;
  border-radius: 12px;
  padding: 23px 25px;
}
.metric > span {
  display: block;
  font-size: 12px;
  color: #6d8375;
}
.metric strong {
  display: block;
  font-size: 36px;
  font-weight: 600;
  margin: 14px 0;
}
.metric small {
  font-size: 11px;
  color: #8d9d93;
}
.two-columns {
  display: grid;
  grid-template-columns: 1.3fr 1fr;
  gap: 24px;
}
.panel {
  background: #fff;
  border: 1px solid #e0e7e2;
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 24px;
}
.panel-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
  gap: 12px;
}
.panel-title h3 {
  margin: 0;
}
.panel-title small,
.muted {
  font-size: 12px;
  color: #809186;
}
.panel-title small {
  display: block;
  margin-top: 8px;
}
.steps {
  padding-left: 22px;
  font-size: 13px;
  line-height: 1.8;
  color: #47705b;
}
.steps li {
  padding: 8px 0 12px 7px;
}
.steps p {
  color: #87958b;
  font-size: 12px;
  margin: 5px 0;
}
.subtle {
  font-size: 11px;
  color: #8d9b92;
  border-top: 1px solid #e8ede9;
  padding-top: 17px;
}
.activity-row {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 18px 0;
  border-top: 1px solid #edf1ee;
  font-size: 13px;
}
.activity-row > div {
  flex: 1;
}
.activity-row strong {
  font-weight: 500;
}
.activity-row small {
  display: block;
  color: #8a9c8e;
  font-size: 11px;
  margin-top: 8px;
}
.activity-row b {
  min-width: 60px;
  font-size: 13px;
}
.toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 20px;
}
.toolbar .el-button + .el-button {
  margin-left: 0;
}
.notice {
  padding: 15px 20px;
  background: #eef5e9;
  color: #627950;
  font-size: 12px;
  line-height: 1.8;
  border-radius: 8px;
  margin-bottom: 22px;
}
.count {
  font-size: 11px;
  font-weight: 400;
  color: #829187;
  margin-left: 10px;
}
.graph-editor {
  margin-top: 20px;
}
.graph-editor p {
  font-size: 12px;
  line-height: 1.8;
  color: #718778;
}
.graph-editor textarea,
.mono,
.json-detail {
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 12px;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 20px;
}
.form-grid .el-select {
  width: 100%;
}
.line-form {
  display: flex;
  gap: 10px;
  margin: 12px 0;
}
.line-form .el-select {
  flex: 1;
  min-width: 130px;
}
.mt {
  margin-top: 20px;
}
.json-detail {
  white-space: pre-wrap;
  line-height: 1.7;
  background: #f6f8f6;
  padding: 18px;
  border-radius: 8px;
}
.detail-metrics {
  display: flex;
  gap: 26px;
  margin: 26px 0;
}
.detail-metrics small {
  display: block;
  font-size: 11px;
  color: #819285;
  margin-bottom: 10px;
}
.detail-metrics strong {
  font-size: 24px;
  font-weight: 600;
}
.reset-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: #7e8e83;
}
footer {
  font-size: 10px;
  color: #95a49b;
  text-align: center;
  margin-top: 30px;
  letter-spacing: 0.5px;
}
.el-table {
  font-size: 12px;
  --el-table-header-bg-color: #f7f9f6;
  --el-table-header-text-color: #718276;
  --el-table-border-color: #edf1ed;
}
.el-table th.el-table__cell {
  height: 44px;
  font-weight: 500;
}
.el-table td.el-table__cell {
  height: 56px;
}
.el-button {
  font-weight: 400;
  font-size: 12px;
}
.el-tag {
  font-size: 11px;
}
.el-progress__text {
  font-size: 11px !important;
}
@media (max-width: 1100px) {
  .sidebar {
    width: 190px;
    padding: 25px 12px;
  }
  .workspace {
    margin-left: 190px;
    width: calc(100% - 190px);
    padding: 26px 22px;
  }
  .intro-art {
    display: none;
  }
  .two-columns {
    grid-template-columns: 1fr;
  }
  .metric-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 700px) {
  .sidebar {
    width: 70px;
    padding: 22px 7px;
  }
  .brand > div,
  .nav-label,
  .sidebar-footer {
    display: none;
  }
  .brand-mark {
    margin: auto;
  }
  nav {
    margin-top: 30px;
  }
  nav button {
    font-size: 0;
    padding: 12px;
    gap: 0;
    justify-content: center;
  }
  nav button span {
    font-size: 24px;
  }
  .workspace {
    margin-left: 70px;
    width: calc(100% - 70px);
    padding: 20px 14px;
  }
  header {
    gap: 10px;
    align-items: flex-start;
  }
  .epoch {
    display: none;
  }
  .header-actions {
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  h1 {
    font-size: 22px;
  }
  .intro {
    padding: 20px;
  }
  .intro h2 {
    font-size: 22px;
  }
  .metric {
    padding: 18px;
  }
  .panel {
    padding: 16px;
  }
  .form-grid {
    grid-template-columns: 1fr;
  }
  .line-form {
    flex-wrap: wrap;
  }
  .el-dialog {
    width: 95% !important;
  }
  .el-drawer {
    width: 95% !important;
  }
}
</style>
