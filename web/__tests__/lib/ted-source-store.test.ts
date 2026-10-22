import { beforeEach, describe, expect, it, vi } from 'vitest'
import { parseSourceAnalysis } from '../../lib/ted'

const { query, read } = vi.hoisted(() => ({ query: vi.fn(), read: vi.fn() }))
vi.mock('../../lib/journal-store', () => ({ queryJournal: query }))
vi.mock('../../lib/ted-store', () => ({ readTedAudienceIssue: read }))
import { readTedSourceDetail } from '../../lib/ted-source-store'

const source = {
  id: 'citation', title: '原始资料', url: 'https://example.org/article/',
  publisher: '发布机构', reason: '本期引用理由，不能冒充逐篇分析。',
}
beforeEach(() => {
  vi.resetAllMocks()
  read.mockResolvedValue({ report: { topics: [{ sources: [source] }] } })
})
describe('TED source analysis', () => {
  it('only resolves sources cited by the requested report', async () => {
    expect(await readTedSourceDetail('issue', 'other')).toBeNull()
    expect(query).not.toHaveBeenCalled()
    read.mockResolvedValue(null)
    expect(await readTedSourceDetail('missing', 'citation')).toBeNull()
  })
  it('uses live article analysis while keeping the editorial citation reason separate', async () => {
    query.mockResolvedValueOnce([{ id: 'real-article', importance_score: 4, reason: '已有分析', hidden_signal: '隐藏信号', tags: ['AI'] }])
    const detail = await readTedSourceDetail('issue', 'citation')
    expect(detail?.record_id).toBe('real-article')
    expect(detail?.analysis?.reason).toBe('已有分析')
    expect(detail?.source.reason).toBe(source.reason)
    expect(query.mock.calls[0][1][0]).toContain('https://example.org/article')
  })
  it('reads enriched policy analysis after the article lookup misses', async () => {
    query.mockResolvedValueOnce([]).mockResolvedValueOnce([{ id: 'policy', ai_relevance: 3, ai_relevance_reason: '政策关联', summary: '政策摘要', enriched_at: '2026-10-22' }])
    const detail = await readTedSourceDetail('issue', 'citation')
    expect(detail?.analysis).toMatchObject({ kind: 'policy', ai_relevance: 3, reason: '政策关联', summary: '政策摘要' })
  })
  it('falls back to actual saved analysis but never invents analysis from citation notes', async () => {
    const snapshot = parseSourceAnalysis({ kind: 'article', reason: '已保存分析' })
    read.mockResolvedValue({ report: { topics: [{ sources: [{ ...source, analysis: snapshot }] }] } })
    query.mockRejectedValueOnce(new Error('record unavailable'))
    expect((await readTedSourceDetail('issue', 'citation'))?.analysis).toEqual(snapshot)
    read.mockResolvedValue({ report: { topics: [{ sources: [source] }] } })
    query.mockResolvedValueOnce([]).mockResolvedValueOnce([])
    expect((await readTedSourceDetail('issue', 'citation'))?.analysis).toBeNull()
  })
  it('validates analysis types and rating ranges', () => {
    expect(parseSourceAnalysis(null)).toBeNull()
    expect(() => parseSourceAnalysis({ kind: 'external' })).toThrow()
    expect(() => parseSourceAnalysis({ kind: 'article', importance_score: 9 })).toThrow()
    expect(parseSourceAnalysis({ kind: 'policy', ai_relevance: 4, summary: '摘要' })?.summary).toBe('摘要')
  })
})
