import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'
import { sameOrigin } from '../../lib/ted-request'

const store = vi.hoisted(() => ({
  create: vi.fn(),
  materials: vi.fn(),
  read: vi.fn(),
  save: vi.fn(),
}))
vi.mock('../../lib/ted-store', () => ({
  createTedIssue: store.create,
  readTedMaterials: store.materials,
  readTedIssue: store.read,
  saveTedIssue: store.save,
  TedConflictError: class extends Error {},
}))
import { POST } from '../../app/api/ted/route'
import { PATCH } from '../../app/api/ted/[id]/route'
import { GET } from '../../app/api/ted/materials/route'

const id = '00000000-0000-4000-8000-000000000001'
function writeRequest(
  path: string,
  method: string,
  body: unknown,
  origin?: string,
  authorization = `Bearer ${"t".repeat(32)}`,
) {
  return new NextRequest(`http://localhost:3424${path}`, {
    method,
    headers: {
      host: 'localhost:3424',
      'Content-Type': 'application/json',
      authorization,
      ...(origin ? { origin } : {}),
    },
    body: JSON.stringify(body),
  })
}
beforeEach(() => { vi.clearAllMocks(); vi.stubEnv('TED_WRITE_TOKEN', 't'.repeat(32)) })
afterEach(() => vi.unstubAllEnvs())

describe('TED background generation access', () => {
  it('reads material candidates without an editor cookie', async () => {
    store.materials.mockResolvedValue({
      materials: [],
      coverage: { articles: 0 },
    })
    const response = await GET(
      new NextRequest(
        'http://localhost:3424/api/ted/materials?start=2026-10-16&end=2026-10-22',
      ),
    )
    expect(response.status).toBe(200)
    expect(store.materials).toHaveBeenCalledWith(
      '2026-10-16',
      '2026-10-22',
      expect.any(String),
    )
  })
  it('creates and saves drafts with server credentials and a matching origin', async () => {
    store.create.mockResolvedValue({ id })
    const created = await POST(
      writeRequest(
        '/api/ted',
        'POST',
        { start: '2026-10-16', end: '2026-10-22' },
        'http://localhost:3424',
      ),
    )
    expect(created.status).toBe(201)
    expect(store.create).toHaveBeenCalledWith('2026-10-16', '2026-10-22')
    store.read.mockResolvedValue({ id })
    store.save.mockResolvedValue({ id, version: 2 })
    const saved = await PATCH(
      writeRequest(
        `/api/ted/${id}`,
        'PATCH',
        { version: 1, action: 'save', report: {} },
        'http://localhost:3424',
      ),
      { params: Promise.resolve({ id }) },
    )
    expect(saved.status).toBe(200)
    expect(store.save).toHaveBeenCalledWith(id, 1, {}, false)
  })
  it('blocks anonymous, incorrect and unconfigured backend writes', async () => {
    for (const authorization of ['', 'Bearer wrong']) {
      expect((await POST(writeRequest('/api/ted', 'POST', {}, 'http://localhost:3424', authorization))).status).toBe(403)
      expect((await PATCH(writeRequest(`/api/ted/${id}`, 'PATCH', {}, 'http://localhost:3424', authorization), { params: Promise.resolve({id}) })).status).toBe(403)
    }
    vi.stubEnv('TED_WRITE_TOKEN', '')
    expect((await POST(writeRequest('/api/ted', 'POST', {}, 'http://localhost:3424'))).status).toBe(403)
    expect(store.create).not.toHaveBeenCalled()
    expect(store.save).not.toHaveBeenCalled()
  })
  it('keeps cross-origin and missing-origin writes blocked', async () => {
    for (const origin of [
      undefined,
      'https://evil.example',
      'https://localhost:3424',
    ]) {
      const request = writeRequest('/api/ted', 'POST', {}, origin)
      expect(sameOrigin(request)).toBe(false)
      expect((await POST(request)).status).toBe(403)
    }
    expect(store.create).not.toHaveBeenCalled()
  })
})
