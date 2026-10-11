import { reactive } from 'vue'

export interface RecordData {
  [key: string]: unknown
  id: number
  version?: number
}
export const session = reactive({ epoch: 1, revision: 1, csrf: '', pending: 0 })
export async function api<T = RecordData>(path: string, method = 'GET', body?: object): Promise<T> {
  session.pending++
  try {
    const response = await fetch(`/api/v1/${path}`, {
      method,
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': session.csrf,
        'Idempotency-Key': crypto.randomUUID(),
      },
      ...(method !== 'GET'
        ? { body: JSON.stringify({ ...body, dataset_epoch: session.epoch }) }
        : {}),
    })
    const result = await response.json()
    if (!response.ok)
      throw new Error(
        `${result.error?.message || '请求失败'}${Object.keys(result.error?.details || {}).length ? ' · ' + JSON.stringify(result.error.details) : ''}`,
      )
    if (result.meta) {
      session.epoch = result.meta.dataset_epoch
      session.revision = result.meta.data_revision
    }
    return result.data as T
  } finally {
    session.pending--
  }
}
export async function bootstrap() {
  const data = await api<{ csrf_token: string; dataset_epoch: number; data_revision: number }>(
    'bootstrap',
  )
  session.csrf = data.csrf_token
  session.epoch = data.dataset_epoch
  session.revision = data.data_revision
}
export const labels: Record<string, string> = {
  FINISHED: '成品',
  SEMI: '半成品',
  RAW: '原料',
  HIGH: '高',
  NORMAL: '普通',
  LOW: '低',
  DRAFT: '草稿',
  ACTIVE: '生效',
  RETIRED: '停用',
  CONFIRMED: '已确认',
  PRODUCTION_COMPLETED: '生产完成',
  CANCELLED: '已取消',
  WAITING: '等待子单',
  READY: '可以生产',
  IN_PROGRESS: '生产中',
  COMPLETED: '完成',
  REVOKED: '已撤销',
  SUPERSEDED: '已替代',
}
