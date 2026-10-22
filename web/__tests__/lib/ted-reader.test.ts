import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'
import { assembleReport, type TedIssue } from '../../lib/ted'

const store = vi.hoisted(() => ({ list: vi.fn(), read: vi.fn() }))
vi.mock('../../lib/ted-store', () => ({
  listTedAudienceIssues: store.list,
  readTedAudienceIssue: store.read,
  createTedIssue: vi.fn(),
  readTedIssue: vi.fn(),
  saveTedIssue: vi.fn(),
  TedConflictError: class extends Error {},
}))
import { GET as listReports } from '../../app/api/ted/route'
import { GET as readReport } from '../../app/api/ted/[id]/route'

const id = '00000000-0000-4000-8000-000000000001'
function issue(): TedIssue {
  const report = assembleReport({
    start_date: '2026-10-16', end_date: '2026-10-22', cutoff_at: '2026-10-22T05:41:00Z',
    coverage: { articles: 10, analyzed: 8, policies: 2, sources: 4, latest_article: null, latest_policy: null },
    materials: [{
      id: 'source:one&two', kind: 'article', title: '原文标题', url: 'https://example.org/article',
      publisher: '机构', published_at: null, date_basis: 'collected', summary: '旧摘要', reason: '引用说明',
      analysis: { kind: 'article', reason: '旧分析快照', importance_score: 4, ai_relevance: null,
        hidden_signal: '', actionable: '', prediction: '', summary: '', source_quote: '', tags: [] },
    }], limit: 240,
  })
  report.title = '周度报告'
  report.intro = '本期导读'
  report.edition_date = '2026-10-23'
  report.next_watch = '已删除的额外跟进章节'
  report.topics[0].host_notes = '内部主持人备注'
  report.topics[0].claim = '判断 [1]'
  report.topics[0].sources[0].reason = '引用说明'
  return { id, report, issue_number: 2, version: 5, published_version: null,
    published_at: null, updated_at: '2026-10-22T07:00:00Z', created_at: '2026-10-22T06:00:00Z' }
}
function request() {
  return new NextRequest(`http://localhost:3424/api/ted/${id}`)
}
const context = { params: Promise.resolve({ id }) }
beforeEach(() => vi.resetAllMocks())

describe('TED agent reading endpoints', () => {
  it('lists audience reports without credentials and gives discoverable detail links', async () => {
    store.list.mockResolvedValue([issue()])
    const response = await listReports()
    expect(response.status).toBe(200)
    expect(response.headers.get('cache-control')).toContain('no-store')
    expect((await response.json()).data).toEqual([expect.objectContaining({
      id, title: '周度报告', edition_date: '2026-10-23', edition_label: '10.23 期', api_url: `/api/ted/${id}`,
    })])
  })
  it('returns report prose and source-analysis links without editorial state or stale analysis', async () => {
    const original = issue()
    store.read.mockResolvedValue(original)
    const response = await readReport(request(), context)
    expect(response.status).toBe(200)
    const { data } = await response.json()
    expect(data.report.topics[0].claim).toBe('判断 [1]')
    expect(data.report.topics[0].sources[0]).toMatchObject({
      reason: '引用说明', date_basis: 'collected',
      analysis_url: `/api/ted/${id}/source?id=source%3Aone%26two`,
    })
    expect(data.report.topics[0]).not.toHaveProperty('host_notes')
    expect(data.report.topics[0].sources[0]).not.toHaveProperty('analysis')
    expect(data.report).not.toHaveProperty('next_watch')
    expect(data.report).not.toHaveProperty('preparation')
    expect(data).not.toHaveProperty('issue_number')
    expect(original.report.topics[0].host_notes).toBe('内部主持人备注')
  })
  it('returns an empty archive or 404 when no audience report is available', async () => {
    store.list.mockResolvedValue([])
    expect(await (await listReports()).json()).toEqual({ data: [] })
    store.read.mockResolvedValue(null)
    const response = await readReport(request(), context)
    expect(response.status).toBe(404)
    expect(await response.json()).toEqual({ error: expect.any(String) })
  })
  it('reports database failures as 503 without exposing error details', async () => {
    store.list.mockRejectedValue(new Error('private database detail'))
    store.read.mockRejectedValue(new Error('private database detail'))
    for (const response of [await listReports(), await readReport(request(), context)]) {
      expect(response.status).toBe(503)
      expect(await response.text()).not.toContain('private database detail')
    }
  })
})
