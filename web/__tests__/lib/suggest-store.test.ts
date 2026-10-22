import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createSuggestion, inspectSource, listSuggestions } from '../../lib/suggest-store'

const { dbQuery, publicFetch } = vi.hoisted(() => ({ dbQuery: vi.fn(), publicFetch: vi.fn() }))
vi.mock('pg', () => ({ Pool: class { query = dbQuery } }))
vi.mock('../../lib/journal-store', () => ({ queryJournal: dbQuery }))
vi.mock('../../lib/public-source-fetch', async (original) => ({
  ...await original<typeof import('../../lib/public-source-fetch')>(), fetchPublicSource: publicFetch,
}))
import { UnsafeSourceUrl } from '../../lib/public-source-fetch'

function rssBody(titles: string[]) {
  const items = titles
    .map((t) => `<item><title>${t}</title><link>https://e/${t.length}</link></item>`)
    .join('')
  return `<?xml version="1.0"?><rss version="2.0"><channel><title>feed</title>${items}</channel></rss>`
}

function mockFetch(body: string, ok = true, status = 200) {
  publicFetch.mockResolvedValue({ status: ok ? 200 : status, body })
  return publicFetch
}

beforeEach(() => {
  vi.unstubAllGlobals()
  dbQuery.mockReset()
  publicFetch.mockReset()
  vi.stubEnv('DATABASE_URL', 'postgres://test')
  vi.stubEnv('API_SOURCE', 'local')
})

describe('inspectSource', () => {
  it('healthy AI rss → rss_ok with keyword ratio', async () => {
    mockFetch(
      rssBody([
        'OpenAI 发布新模型',
        '大模型推理加速',
        '智能体框架对比',
        '机器学习教程',
        'AI 芯片动态',
        '版本更新说明',
        '社区公告',
        '招聘信息',
        '周报',
        '其他动态',
      ]),
    )
    const h = await inspectSource('https://e/feed', 'tech')
    expect(h.verdict).toBe('rss_ok')
    expect(h.items).toBe(10)
    expect(h.ai_keyword_ratio as number).toBeGreaterThan(0.4)
    expect(h.sample_titles?.length).toBe(5)
  })

  it('policy rss counts policy keywords', async () => {
    mockFetch(rssBody(['关于印发办法的通知', '征集意见', '无关动态', '规划解读', '公告']))
    const h = await inspectSource('https://e/p', 'policy')
    expect(h.verdict).toBe('rss_ok')
    expect((h.ai_keyword_ratio ?? 0) as number).toBeGreaterThan(0.3)
  })

  it('js shell html → js_shell verdict', async () => {
    mockFetch('<html><div id="root"></div></html>')
    const h = await inspectSource('https://e/x', 'policy')
    expect(h.verdict).toBe('js_shell')
  })

  it('server-rendered list page → html_candidate', async () => {
    const links = Array.from({ length: 20 }, (_, i) => `<a href="/a${i}">通知公告${i}</a>`).join('')
    mockFetch(`<html><body>${links}${'内容'.repeat(2000)}</body></html>`)
    const h = await inspectSource('https://e/x', 'policy')
    expect(h.verdict).toBe('html_candidate')
  })

  it('http error / network failure → unreachable', async () => {
    mockFetch('', false, 403)
    expect((await inspectSource('https://e/403', 'tech')).verdict).toBe('unreachable')
    publicFetch.mockRejectedValue(Object.assign(new Error('t'), { name: 'TimeoutError' }))
    expect((await inspectSource('https://e/t', 'tech')).verdict).toBe('unreachable')
  })
})


describe('suggestion persistence boundary', () => {
  it('treats an uninitialized suggestion table as empty but propagates outages', async () => {
    dbQuery.mockRejectedValueOnce({ code: '42P01' })
    expect(await listSuggestions()).toEqual([])
    dbQuery.mockRejectedValueOnce(new Error('database unavailable'))
    await expect(listSuggestions()).rejects.toThrow('database unavailable')
  })

  it('does not persist prohibited source addresses or suppressed network-policy errors', async () => {
    await expect(createSuggestion({ url: 'http://127.0.0.1/' })).rejects.toBeInstanceOf(UnsafeSourceUrl)
    expect(publicFetch).not.toHaveBeenCalled()
    expect(dbQuery).not.toHaveBeenCalled()
    publicFetch.mockRejectedValue(new UnsafeSourceUrl('blocked DNS result'))
    await expect(createSuggestion({ url: 'https://example.org/rss' })).rejects.toBeInstanceOf(UnsafeSourceUrl)
    expect(dbQuery).not.toHaveBeenCalled()
  })
  it('stores health only after a permitted inspection and canonicalizes the source URL', async () => {
    mockFetch(rssBody(['模型', '智能体', 'AI 芯片', '推理', 'OpenAI 发布']))
    dbQuery.mockResolvedValueOnce([]).mockResolvedValueOnce([{ id: 1, url: 'https://example.org/rss' }])
    await createSuggestion({ url: 'https://example.org:443/rss#top', name: '官方源' })
    expect(dbQuery.mock.calls[1][1][0]).toBe('https://example.org/rss')
    expect(JSON.parse(dbQuery.mock.calls[1][1][5]).verdict).toBe('rss_ok')
  })
})
