import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  safeUrl,
  diverseArticles,
  insightItems,
  dateLabel,
} from '../../lib/journal-utils'
import type { Row } from '../../app/types'
const { dbQuery } = vi.hoisted(() => ({ dbQuery: vi.fn() }))
vi.mock('pg', () => ({
  Pool: class {
    query = dbQuery
  },
}))
import {
  readPolicies,
  readSignals,
  relatedPolicies,
} from '../../lib/journal-store'
beforeEach(() => {
  dbQuery.mockReset()
  vi.stubEnv('LOCAL_DB_URL', 'postgres://test')
  vi.stubEnv('API_SOURCE', 'local')
})
describe('reading safety and selection', () => {
  it('rejects unsafe stored links while allowing external sources', () => {
    expect(safeUrl('javascript:alert(1)')).toBeUndefined()
    expect(safeUrl('data:text/html,test')).toBeUndefined()
    expect(safeUrl('/relative')).toBeUndefined()
    expect(safeUrl('https://example.org/a')).toBe('https://example.org/a')
  })
  it('keeps source variety and removes duplicated URLs', () => {
    const row = (id: string, source: string, url = id): Row => ({
      id,
      source,
      url,
      title: id,
      time: '2026-09-18T00:00:00Z',
    })
    const selected = diverseArticles(
      [
        row('1', 'A'),
        row('2', 'A'),
        row('3', 'A'),
        row('4', 'B'),
        row('5', 'C'),
        row('6', 'C', '4'),
      ],
      4,
    )
    expect(selected.map((r) => r.id)).toEqual(['1', '2', '4', '5'])
  })
  it('normalizes mixed insight versions and excludes unsafe source links', () => {
    expect(
      insightItems([
        ' text ',
        {
          text: 'new',
          source_urls: ['javascript:alert(1)', 'https://example.org'],
        },
        null,
        { title: 'legacy', content: 'body' },
      ]),
    ).toEqual([
      { text: 'text' },
      { text: 'new', source_urls: ['https://example.org'], source_titles: [] },
      { text: 'body', source_urls: [], source_titles: [] },
    ])
  })
  it('formats calendar dates consistently across time zones', () => {
    expect(dateLabel('2026-09-18T20:00:00Z')).toContain('2026/09/19')
    expect(dateLabel('bad')).toBe('未记录')
  })
})
describe('policy and signal query boundaries', () => {
  it('rejects impossible dates before contacting the database', async () => {
    await expect(
      readSignals(new URLSearchParams({ date: '2026-02-31' })),
    ).rejects.toThrow('Invalid date')
    expect(dbQuery).not.toHaveBeenCalled()
  })
  it('parameterizes policy filters and uses database total for pagination', async () => {
    dbQuery
      .mockResolvedValueOnce({ rows: [{ total: 31 }] })
      .mockResolvedValueOnce({ rows: [] })
    const term = "x' OR 1=1 --"
    const result = await readPolicies(
      new URLSearchParams({
        search: term,
        region: '北京',
        stage: '已发布',
        mode: 'relevant',
        page: '2',
      }),
    )
    const [sql, values] = dbQuery.mock.calls[1]
    expect(sql).not.toContain(term)
    expect(sql).toContain('ai_relevance >= 4')
    expect(sql).toContain('enriched_at IS NOT NULL')
    expect(values).toEqual([
      `%${term}%`,
      term.toLowerCase(),
      '北京',
      '已发布',
      expect.any(String),
      30,
    ])
    expect(result).toMatchObject({
      data: [],
      total: 31,
      page: 2,
      hasMore: false,
      nextCursor: null,
    })
  })
  it('applies high importance and tag filters before paginating, preserving offset times', async () => {
    dbQuery
      .mockResolvedValueOnce({ rows: [{ total: 1 }] })
      .mockResolvedValueOnce({
        rows: [
          {
            id: 'one',
            title: 'Example',
            url: 'https://example.org',
            source_feed_name: 'Source',
            display_time: '2026-09-18T20:00:00Z',
            tags: ['AI'],
          },
        ],
      })
    const result = await readSignals(
      new URLSearchParams({
        mode: 'high',
        tag: 'AI',
        date: '2026-09-19',
        page: '-4',
      }),
    )
    const [sql, values] = dbQuery.mock.calls[1]
    expect(sql).toContain('importance_score >= 4')
    expect(sql).toContain("AT TIME ZONE 'Asia/Shanghai'")
    expect(values).toEqual(['["AI"]', '2026-09-19', expect.any(String)])
    expect(result.data[0].time).toBe('2026-09-18T20:00:00Z')
    expect(result.page).toBe(1)
    expect(result.hasMore).toBe(false)
  })
  it('does not query associations without meaningful keywords', async () => {
    expect(await relatedPolicies(['', 'a'])).toEqual([])
    expect(dbQuery).not.toHaveBeenCalled()
  })
  it('escapes wildcard keywords in candidate policy associations', async () => {
    dbQuery.mockResolvedValue({ rows: [] })
    await relatedPolicies(['AI_100%'])
    expect(dbQuery.mock.calls[0][1]).toEqual([['%AI\\_100\\%%']])
  })
})
