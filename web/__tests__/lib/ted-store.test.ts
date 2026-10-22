import { beforeEach, describe, expect, it, vi } from 'vitest'
import { assembleReport, type TedIssue, type TedMaterials } from '../../lib/ted'
const { query } = vi.hoisted(() => ({ query: vi.fn() }))
vi.mock('../../lib/journal-store', () => ({ queryJournal: query }))
import {
  listTedIssues,
  readTedIssue,
  readTedMaterials,
  saveTedIssue,
  readTedAudienceIssue,
  listTedAudienceIssues,
} from '../../lib/ted-store'

const packet: TedMaterials = {
  start_date: '2026-09-12',
  end_date: '2026-09-18',
  cutoff_at: '2026-09-19T00:00:00Z',
  coverage: {
    articles: 10,
    policies: 2,
    analyzed: 8,
    sources: 4,
    latest_article: null,
    latest_policy: null,
  },
  materials: [],
  limit: 240,
}
const id = '00000000-0000-4000-8000-000000000001'
function issue(): TedIssue {
  return {
    id,
    issue_number: 1,
    version: 1,
    published_version: null,
    published_at: null,
    updated_at: '',
    created_at: '',
    report: assembleReport(packet),
  }
}
beforeEach(() => query.mockReset())
describe('TED persistence and publication boundaries', () => {
  it('reads prepared reports without exposing presenter notes', async () => {
    const prepared = issue()
    prepared.report.title = '本期报告'
    prepared.report.topics = [
      {
        id: 'one',
        title: '议题',
        claim: '判断',
        body: '',
        uncertainty: '',
        watch: '',
        host_notes: '内部备注',
        image: null,
        sources: [],
      },
    ]
    query.mockResolvedValueOnce([prepared])
    const audience = await readTedAudienceIssue(id)
    expect(audience!.report.topics[0].host_notes).toBe('')
    expect(prepared.report.topics[0].host_notes).toBe('内部备注')
    query.mockResolvedValueOnce([issue()])
    expect(await readTedAudienceIssue(id)).toBeNull()
  })
  it('excludes untitled material drafts from the reading archive', async () => {
    query.mockResolvedValueOnce([])
    expect(await listTedAudienceIssues()).toEqual([])
    expect(query.mock.calls[0][0]).toContain(
      "NULLIF(btrim(draft->>'title'),'') IS NOT NULL",
    )
    expect(query.mock.calls[0][0]).toContain(
      "'edition_date',draft->'edition_date'",
    )
  })
  it('treats an uninitialized archive as empty but propagates database outages', async () => {
    query.mockRejectedValueOnce({ code: '42P01' })
    expect(await listTedIssues()).toEqual([])
    query.mockRejectedValueOnce(new Error('offline'))
    await expect(listTedIssues()).rejects.toThrow('offline')
  })
  it('loads only published snapshots for audience requests', async () => {
    query.mockResolvedValueOnce([])
    expect(await readTedIssue(id)).toBeNull()
    expect(query.mock.calls[0][0]).toContain('AND published IS NOT NULL')
    expect(query.mock.calls[0][0]).toContain('published AS report')
    expect(await readTedIssue('invalid')).toBeNull()
    expect(query).toHaveBeenCalledTimes(1)
  })
  it('applies timezone and ingestion cutoff before ranking material candidates', async () => {
    query
      .mockResolvedValueOnce([packet.coverage])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([])
    await readTedMaterials(packet.start_date, packet.end_date, packet.cutoff_at)
    for (const [sql, params] of query.mock.calls) {
      expect(sql).toContain('$3::timestamptz')
      expect(params).toEqual([
        '2026-09-12T00:00:00+08:00',
        '2026-09-18T16:00:00.000Z',
        packet.cutoff_at,
      ])
    }
    expect(query.mock.calls[1][0]).toContain('row_number() OVER')
    expect(query.mock.calls[2][0]).toContain('policy_documents')
  })
  it('keeps published content intact on a draft save and preserves coverage metadata', async () => {
    const before = issue(),
      input = structuredClone(before.report)
    input.coverage.articles = 999
    query
      .mockResolvedValueOnce([before])
      .mockResolvedValueOnce([{ id }])
      .mockResolvedValueOnce([before])
    await saveTedIssue(id, 1, input, false)
    const [sql, params] = query.mock.calls[1]
    expect(sql).toContain('WHERE id=$1 AND version=$2')
    expect(sql).toContain('ELSE published END')
    expect(JSON.parse(params[2]).coverage.articles).toBe(10)
    expect(params[3]).toBe(false)
  })
  it('does not overwrite a concurrent save or stale tab', async () => {
    const before = issue()
    query.mockResolvedValueOnce([before]).mockResolvedValueOnce([])
    await expect(saveTedIssue(id, 1, before.report, false)).rejects.toThrow(
      '没有覆盖',
    )
    query.mockReset()
    query.mockResolvedValueOnce([{ ...before, version: 2 }])
    await expect(saveTedIssue(id, 1, before.report, false)).rejects.toThrow(
      '其他窗口',
    )
    expect(query).toHaveBeenCalledTimes(1)
  })
})
