import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, bootstrap, session } from '../../src/api'
afterEach(() => {
  vi.unstubAllGlobals()
  session.pending = 0
})
describe('same-origin API boundary', () => {
  it('loads CSRF and the current data epoch before writing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          data: { csrf_token: 'temporary-token', dataset_epoch: 4, data_revision: 9 },
          meta: { dataset_epoch: 4, data_revision: 9 },
        }),
      }),
    )
    await bootstrap()
    expect(session.csrf).toBe('temporary-token')
    expect(session.epoch).toBe(4)
  })
  it('writes with CSRF, epoch, decimal strings and an idempotency key', async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ data: { id: 1 }, meta: { dataset_epoch: 4, data_revision: 10 } }),
    })
    vi.stubGlobal('fetch', fetch)
    session.csrf = 'test'
    session.epoch = 4
    await api('production-orders/1/progress', 'POST', {
      expected_version: 2,
      own_progress: '60.01',
    })
    const [path, options] = fetch.mock.calls[0]!
    expect(path).toBe('/api/v1/production-orders/1/progress')
    expect(options.headers['X-CSRFToken']).toBe('test')
    expect(options.headers['Idempotency-Key']).toBeTruthy()
    expect(JSON.parse(options.body)).toEqual({
      expected_version: 2,
      own_progress: '60.01',
      dataset_epoch: 4,
    })
    expect(session.pending).toBe(0)
  })
  it('keeps the old epoch on a rejected request and exposes its reason', async () => {
    session.epoch = 4
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        json: async () => ({
          error: { code: 'STALE_EPOCH', message: '演示数据已重置', details: {} },
        }),
      }),
    )
    await expect(api('items', 'POST', {})).rejects.toThrow('演示数据已重置')
    expect(session.epoch).toBe(4)
    expect(session.pending).toBe(0)
  })
})
