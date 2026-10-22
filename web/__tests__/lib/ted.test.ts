import { describe, expect, it } from 'vitest'
import {
  assembleReport,
  defaultWindow,
  groupMaterials,
  parseReport,
  publicReport,
  removeTopicSource,
  sourceKey,
  validateWindow,
  tedEditionLabel,
  type TedMaterials,
  type TedSource,
} from '../../lib/ted'

const source: TedSource = {
  id: 'a',
  kind: 'article',
  title: '原始报道',
  url: 'https://example.org/report',
  publisher: '研究机构',
  published_at: '2026-09-18T06:00:00Z',
  date_basis: 'published',
  summary: '这是逐篇分析，不是整周的综合判断。',
  reason: '',
  cluster_id: 1,
  cluster_label: '模型工具',
}
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
  materials: [source],
  limit: 240,
}
function ready() {
  const report = assembleReport(packet)
  report.title = '本周观察'
  report.intro = '讨论模型工具的变化。'
  report.topics[0].claim = '值得关注的判断 [1]。'
  report.topics[0].sources[0].reason = '支撑关键事件的发生。'
  return report
}

describe('TED editorial contract', () => {
  it('names editions by their date instead of an internal sequence', () => {
    expect(tedEditionLabel({ ...ready(), edition_date: '2026-10-23' })).toBe(
      '10.23 期',
    )
    expect(
      tedEditionLabel({ ...ready(), live_at: '2026-10-22T18:00:00Z' }),
    ).toBe('10.23 期')
    expect(tedEditionLabel({ ...ready(), end_date: '2026-12-31' })).toBe(
      '01.01 期',
    )
    expect(
      parseReport({ ...ready(), edition_date: '2026-10-23' }).edition_date,
    ).toBe('2026-10-23')
    expect(() =>
      parseReport({ ...ready(), edition_date: '2026-02-30' }),
    ).toThrow()
  })
  it('uses inclusive Shanghai days and rejects impossible or excessive windows', () => {
    expect(validateWindow('2026-09-12', '2026-09-18')).toEqual({
      start: '2026-09-12T00:00:00+08:00',
      end: '2026-09-18T16:00:00.000Z',
    })
    for (const [start, end] of [
      ['2026-02-30', '2026-03-01'],
      ['2026-09-20', '2026-09-18'],
      ['2026-08-01', '2026-09-18'],
    ])
      expect(() => validateWindow(start, end)).toThrow()
    expect(defaultWindow(new Date('2026-09-19T17:00:00Z'))).toEqual({
      start: '2026-09-13',
      end: '2026-09-19',
    })
  })
  it('assembles cited candidates without inventing a weekly judgment', () => {
    const report = assembleReport(packet)
    expect(report.topics[0].title).toBe('模型工具')
    expect(report.topics[0].claim).toBe('')
    expect(report.topics[0].sources[0].summary).toContain('逐篇分析')
    expect(parseReport(report).topics).toHaveLength(1)
    expect(() => parseReport(report, true)).toThrow()
  })
  it('deduplicates tracking URL variants and keeps a policy candidate', () => {
    expect(sourceKey({ url: source.url + '?utm_source=feed#top' })).toBe(
      source.url,
    )
    const materials = [
      source,
      { ...source, id: 'b', url: source.url + '?utm_source=rss' },
      {
        ...source,
        kind: 'policy' as const,
        cluster_id: null,
        cluster_label: null,
        id: 'p',
        url: 'https://gov.example/policy',
      },
    ]
    expect(
      groupMaterials(materials).map((topic) => topic.sources.length),
    ).toEqual([1, 1])
    expect(
      assembleReport({ ...packet, materials }).topics.some(
        (topic) => topic.sources[0].kind === 'policy',
      ),
    ).toBe(true)
  })
  it('requires evidence, citation reasons, and valid citation numbers before publication', () => {
    expect(parseReport(ready(), true).title).toBe('本周观察')
    const noReason = ready()
    noReason.topics[0].sources[0].reason = ''
    expect(() => parseReport(noReason, true)).toThrow('支持了哪一点')
    const missing = ready()
    missing.topics[0].claim = '未被支持 [2]'
    expect(() => parseReport(missing, true)).toThrow('不存在的资料')
    const noEvidence = ready()
    noEvidence.topics[0].sources = []
    noEvidence.topics[0].claim = '判断'
    expect(() => parseReport(noEvidence, true)).toThrow('至少一条')
  })
  it('rejects unsafe URLs, duplicate topics and oversized payload fields', () => {
    const bad = ready()
    bad.topics[0].sources[0].url = 'javascript:alert(1)'
    expect(() => parseReport(bad)).toThrow('http(s)')
    const dup = ready()
    dup.topics.push({ ...dup.topics[0] })
    expect(() => parseReport(dup)).toThrow('不能重复')
    const image = ready()
    image.cover = { url: 'https://example.org/cover.png', alt: '' }
    expect(() => parseReport(image)).toThrow('图片说明')
    expect(() => parseReport({ ...ready(), intro: 'x'.repeat(5001) })).toThrow()
  })
  it('strips host notes from public snapshots without mutating the draft', () => {
    const draft = ready()
    draft.topics[0].host_notes = '主持人内部备注'
    expect(publicReport(draft).topics[0].host_notes).toBe('')
    expect(draft.topics[0].host_notes).toBe('主持人内部备注')
  })
  it('keeps citation meaning when removing sources and prevents removing referenced evidence', () => {
    const topic = ready().topics[0]
    topic.sources.push({
      ...source,
      id: 'b',
      url: 'https://example.org/second',
    })
    expect(() => removeTopicSource(topic, 0)).toThrow('先移除正文中的引用')
    topic.claim = '第二条支持 [2]'
    const updated = removeTopicSource(topic, 0)
    expect(updated.claim).toBe('第二条支持 [1]')
    expect(updated.sources[0].id).toBe('b')
  })
})
