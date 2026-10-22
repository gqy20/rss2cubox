import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { EventEmitter } from 'node:events'
import { PassThrough } from 'node:stream'

const { dns, request } = vi.hoisted(() => ({ dns: vi.fn(), request: vi.fn() }))
vi.mock('node:dns/promises', () => ({ lookup: dns, default: { lookup: dns } }))
vi.mock('node:http', () => ({ request, default: { request } }))
vi.mock('node:https', () => ({ request, default: { request } }))
import { fetchPublicSource, publicSourceUrl, isPublicSourceAddress, UnsafeSourceUrl } from '../../lib/public-source-fetch'

type Reply = { status?: number; headers?: Record<string, string | undefined>; chunks?: Buffer[]; stall?: boolean; delay?: number }
let replies: Reply[] = []
let responses: PassThrough[] = []

beforeEach(() => {
  vi.clearAllMocks()
  replies = []
  responses = []
  dns.mockResolvedValue([{ address: '93.184.216.34', family: 4 }])
  request.mockImplementation((_url, options, callback) => {
    const req = Object.assign(new EventEmitter(), { destroyed: false, end: vi.fn(), destroy: vi.fn() })
    let response: PassThrough | undefined
    let timer: ReturnType<typeof setTimeout> | undefined
    req.destroy.mockImplementation((error?: Error) => {
      if (req.destroyed) return req
      req.destroyed = true
      if (timer) clearTimeout(timer)
      response?.destroy()
      if (error) req.emit('error', error)
      return req
    })
    options.signal.addEventListener('abort', () => req.destroy(new Error('source_timeout')), { once: true })
    req.end.mockImplementation(() => {
      const reply = replies.shift() || { chunks: [Buffer.from('feed')] }
      const send = () => {
        if (req.destroyed) return
        response = Object.assign(new PassThrough(), { statusCode: reply.status || 200, headers: reply.headers || {} })
        responses.push(response)
        callback(response)
        if (response.destroyed || reply.stall) return
        for (const chunk of reply.chunks || [Buffer.from('feed')]) {
          if (response.destroyed || req.destroyed) break
          response.write(chunk)
        }
        if (!response.destroyed) response.end()
      }
      if (reply.delay) timer = setTimeout(send, reply.delay)
      else queueMicrotask(send)
    })
    return req
  })
})
afterEach(() => vi.useRealTimers())

describe('public source address policy (no network probes)', () => {
  it.each([
    '0.0.0.0', '10.1.2.3', '127.0.0.1', '100.100.100.200', '169.254.169.254',
    '172.16.1.1', '192.168.1.1', '192.0.0.1', '192.0.2.1', '198.18.0.1',
    '198.51.100.1', '203.0.113.1', '224.0.0.1', '255.255.255.255', '168.63.129.16',
    '::', '::1', '::ffff:127.0.0.1', '::ffff:8.8.8.8', 'fc00::1', 'fe80::1',
    '64:ff9b::a00:1', '2002:7f00:1::1', '2001:db8::1', '2001::1', '3fff::1', 'ff02::1',
  ])('rejects special address %s', (address) => expect(isPublicSourceAddress(address)).toBe(false))

  it.each(['93.184.216.34', '8.8.8.8', '2606:4700:4700::1111', '2001:4860:4860::8888'])(
    'permits public unicast %s', (address) => expect(isPublicSourceAddress(address)).toBe(true),
  )
  it.each([
    'http://127.1/', 'http://2130706433/', 'http://0x7f000001/', 'http://0177.0.0.1/',
    'http://[::ffff:7f00:1]/', 'http://localhost./', 'http://host.local/', 'http://metadata.google.internal/',
    'http://service/', 'https://user:password@example.org/', 'https://example.org:8080/',
    'http://example.org:443/', 'file:///etc/passwd', 'gopher://example.org/', 'https://example.org\\@127.0.0.1/',
  ])('rejects unsafe or ambiguous URL %s before DNS', (url) => {
    expect(() => publicSourceUrl(url)).toThrow(UnsafeSourceUrl)
    expect(dns).not.toHaveBeenCalled()
    expect(request).not.toHaveBeenCalled()
  })
})

describe('DNS pinning, redirect and resource boundaries', () => {
  it('validates both address families and pins the approved address without a second DNS lookup', async () => {
    dns.mockResolvedValueOnce([{ address: '93.184.216.34', family: 4 }])
      .mockResolvedValueOnce([{ address: '127.0.0.1', family: 4 }])
    expect(await fetchPublicSource('https://example.org/rss')).toMatchObject({ status: 200, body: 'feed' })
    expect(dns).toHaveBeenCalledTimes(1)
    const [url, options] = request.mock.calls[0]
    expect(url.hostname).toBe('example.org')
    expect(options).toMatchObject({ agent: false, autoSelectFamily: false, servername: 'example.org', rejectUnauthorized: true })
    const callback = vi.fn()
    options.lookup('example.org', {}, callback)
    expect(callback).toHaveBeenCalledWith(null, '93.184.216.34', 4)
    options.lookup('example.org', { all: true }, callback)
    expect(callback).toHaveBeenLastCalledWith(null, [{ address: '93.184.216.34', family: 4 }])
    expect(dns).toHaveBeenCalledTimes(1)
    expect(options.headers).not.toHaveProperty('authorization')
    expect(options.headers).not.toHaveProperty('cookie')
  })
  it('rejects mixed public/private DNS answers before establishing any HTTP connection', async () => {
    dns.mockResolvedValue([{ address: '93.184.216.34', family: 4 }, { address: 'fc00::1', family: 6 }])
    await expect(fetchPublicSource('https://example.org/rss')).rejects.toBeInstanceOf(UnsafeSourceUrl)
    expect(request).not.toHaveBeenCalled()
  })
  it('checks redirect targets before connecting to them', async () => {
    replies.push({ status: 302, headers: { location: 'https://169.254.169.254/not-requested' } })
    await expect(fetchPublicSource('https://example.org/rss')).rejects.toBeInstanceOf(UnsafeSourceUrl)
    expect(request).toHaveBeenCalledTimes(1)
  })
  it('resolves and validates each hop, including same-host rebinding on a relative redirect', async () => {
    replies.push({ status: 302, headers: { location: '/next' } })
    dns.mockResolvedValueOnce([{ address: '93.184.216.34', family: 4 }])
      .mockResolvedValueOnce([{ address: '10.0.0.1', family: 4 }])
    await expect(fetchPublicSource('https://example.org/rss')).rejects.toBeInstanceOf(UnsafeSourceUrl)
    expect(dns).toHaveBeenCalledTimes(2)
    expect(request).toHaveBeenCalledTimes(1)
  })
  it('follows a permitted redirect with a freshly pinned public address', async () => {
    replies.push({ status: 301, headers: { location: 'https://other.example.org/feed' } }, { chunks: [Buffer.from('<rss/>')] })
    dns.mockResolvedValueOnce([{ address: '93.184.216.34', family: 4 }])
      .mockResolvedValueOnce([{ address: '8.8.8.8', family: 4 }])
    expect((await fetchPublicSource('https://example.org/rss')).body).toBe('<rss/>')
    expect(request.mock.calls[1][0].hostname).toBe('other.example.org')
    const callback = vi.fn()
    request.mock.calls[1][1].lookup('other.example.org', {}, callback)
    expect(callback).toHaveBeenCalledWith(null, '8.8.8.8', 4)
  })
  it('blocks downgrade, redirect loops and excess hops', async () => {
    replies.push({ status: 302, headers: { location: 'http://example.org/feed' } })
    await expect(fetchPublicSource('https://example.org/rss')).rejects.toBeInstanceOf(UnsafeSourceUrl)
    replies.push({ status: 302, headers: { location: '/rss' } })
    await expect(fetchPublicSource('https://example.org/rss')).rejects.toBeInstanceOf(UnsafeSourceUrl)
    replies.push(...[1, 2, 3, 4].map((n) => ({ status: 302, headers: { location: `/hop${n}` } })))
    await expect(fetchPublicSource('https://example.org/rss')).rejects.toBeInstanceOf(UnsafeSourceUrl)
    expect(request).toHaveBeenCalledTimes(6)
  })
  it('enforces the response byte cap while streaming even without Content-Length', async () => {
    replies.push({ chunks: [Buffer.alloc(250_000), Buffer.alloc(200_000)] })
    await expect(fetchPublicSource('https://example.org/rss')).rejects.toThrow('source_response_limit')
    expect(responses[0].destroyed).toBe(true)
  })
  it.each([{ 'content-length': '400001' }, { 'content-encoding': 'gzip' }])('rejects oversized or compressed bodies from headers', async (headers) => {
    replies.push({ headers })
    await expect(fetchPublicSource('https://example.org/rss')).rejects.toThrow('source_response_limit')
    expect(responses[0].destroyed).toBe(true)
  })
  it('times out a stalled DNS lookup without making an HTTP request', async () => {
    vi.useFakeTimers()
    dns.mockImplementation(() => new Promise(() => {}))
    const done = expect(fetchPublicSource('https://example.org/rss')).rejects.toThrow('source_timeout')
    await vi.advanceTimersByTimeAsync(10_001)
    await done
    expect(request).not.toHaveBeenCalled()
  })
  it('keeps the deadline active after headers until the response body ends', async () => {
    vi.useFakeTimers()
    replies.push({ stall: true })
    const done = expect(fetchPublicSource('https://example.org/rss')).rejects.toThrow('source_timeout')
    await vi.advanceTimersByTimeAsync(10_001)
    await done
    expect(responses[0].destroyed).toBe(true)
  })
  it('shares one deadline across redirects instead of resetting each hop', async () => {
    vi.useFakeTimers()
    replies.push({ status: 302, headers: { location: '/next' }, delay: 6000 }, { delay: 6000 })
    const done = expect(fetchPublicSource('https://example.org/rss')).rejects.toThrow('source_timeout')
    await vi.advanceTimersByTimeAsync(10_001)
    await done
    expect(request).toHaveBeenCalledTimes(2)
    expect(request.mock.calls[0][1].signal).toBe(request.mock.calls[1][1].signal)
  })
})
