import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'
import { UnsafeSourceUrl } from '../../lib/public-source-fetch'

const { create, list } = vi.hoisted(() => ({ create: vi.fn(), list: vi.fn() }))
vi.mock('../../lib/suggest-store', () => ({ createSuggestion: create, listSuggestions: list }))
import { GET, POST } from '../../app/api/suggest-source/route'

const token = 's'.repeat(48)
function request(body?: unknown, credential: string | null = `Bearer ${token}`) {
  return new NextRequest('http://localhost:3424/api/suggest-source', {
    method: body === undefined ? 'GET' : 'POST',
    headers: { ...(credential ? { authorization: credential } : {}), 'content-type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
}
beforeEach(() => { vi.clearAllMocks(); vi.stubEnv('SOURCE_SUGGEST_TOKEN', token) })
afterEach(() => vi.unstubAllEnvs())

describe('source suggestion maintainer boundary', () => {
  it('blocks anonymous and incorrect credentials before reading payloads or touching storage', async () => {
    for (const credential of [null, 'Bearer incorrect', `Basic ${token}`]) {
      expect((await GET(request(undefined, credential))).status).toBe(401)
      const req = request({ url: 'https://example.org/rss' }, credential)
      expect((await POST(req)).status).toBe(401)
      expect(req.bodyUsed).toBe(false)
    }
    expect(list).not.toHaveBeenCalled()
    expect(create).not.toHaveBeenCalled()
  })
  it('fails closed when credentials are missing or too short', async () => {
    for (const value of ['', 'short']) {
      vi.stubEnv('SOURCE_SUGGEST_TOKEN', value)
      expect((await GET(request())).status).toBe(401)
      expect((await POST(request({ url: 'https://example.org/rss' }))).status).toBe(401)
    }
    expect(create).not.toHaveBeenCalled()
  })
  it('does not accept credentials from query parameters or cookies', async () => {
    const req = new NextRequest(`http://localhost:3424/api/suggest-source?token=${token}`, { headers: { cookie: `token=${token}` } })
    expect((await GET(req)).status).toBe(401)
    expect(list).not.toHaveBeenCalled()
  })
  it('allows authorized review and submission without adding a frontend login flow', async () => {
    list.mockResolvedValue([{ id: 1 }])
    expect((await GET(request())).status).toBe(200)
    create.mockResolvedValue({ id: 2 })
    const response = await POST(request({ url: 'https://example.org:443/rss#top', kind: 'tech' }))
    expect(response.status).toBe(200)
    expect(create).toHaveBeenCalledWith(expect.objectContaining({ url: 'https://example.org/rss', kind: 'tech' }))
    expect(response.headers.get('cache-control')).toBe('no-store')
  })
  it.each([null, [], 'text', { url: 'file:///etc/passwd' }, { url: 'http://127.0.0.1/' },
    { url: 'https://example.org/rss', kind: 'other' }])('rejects invalid input %j before storage', async (body) => {
    expect((await POST(request(body))).status).toBe(400)
    expect(create).not.toHaveBeenCalled()
  })
  it('limits actual body bytes even when Content-Length is absent', async () => {
    const response = await POST(request({ url: 'https://example.org/rss', note: 'x'.repeat(9000) }))
    expect(response.status).toBe(413)
    expect(create).not.toHaveBeenCalled()
  })
  it('returns blocked redirect/DNS errors as 400 instead of saving an unreachable suggestion', async () => {
    create.mockRejectedValue(new UnsafeSourceUrl('信源地址必须指向公网。'))
    const response = await POST(request({ url: 'https://example.org/rss' }))
    expect(response.status).toBe(400)
  })
  it('does not expose backend error details', async () => {
    const log = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      create.mockRejectedValue(new Error('private database credentials'))
      const response = await POST(request({ url: 'https://example.org/rss' }))
      expect(response.status).toBe(503)
      expect(await response.text()).not.toContain('private database credentials')
      expect(JSON.stringify(log.mock.calls)).not.toContain('private database credentials')
    } finally { log.mockRestore() }
  })
})
