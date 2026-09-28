import { beforeEach, describe, expect, it, vi } from 'vitest'
import { inspectSource } from '../../lib/suggest-store'

const { dbQuery } = vi.hoisted(() => ({ dbQuery: vi.fn() }))
vi.mock('pg', () => ({ Pool: class { query = dbQuery } }))
vi.mock('../../lib/journal-store', () => ({ query: dbQuery }))

function rssBody(titles: string[]) {
  const items = titles
    .map((t) => `<item><title>${t}</title><link>https://e/${t.length}</link></item>`)
    .join('')
  return `<?xml version="1.0"?><rss version="2.0"><channel><title>feed</title>${items}</channel></rss>`
}

function mockFetch(body: string, ok = true, status = 200) {
  const fn = vi.fn().mockResolvedValue({
    ok,
    status,
    text: () => Promise.resolve(body),
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

beforeEach(() => {
  vi.unstubAllGlobals()
  dbQuery.mockReset()
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
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(Object.assign(new Error('t'), { name: 'TimeoutError' })),
    )
    expect((await inspectSource('https://e/t', 'tech')).verdict).toBe('unreachable')
  })
})
