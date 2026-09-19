import { describe, it, expect } from 'vitest'
import {
  safeReturnPath,
  withOrigin,
  articleDestination,
  policyDestination,
  returnLabel,
  insightFreshness,
} from '../../lib/reading-context'
describe('reading context navigation', () => {
  it('keeps the same topic for single-article and full-topic reading', () => {
    const url = new URL(
      articleDestination('article-1', {
        from: '/topics?id=3',
        filters: { topic: '3' },
      }),
      'https://local.test',
    )
    expect(url.pathname).toBe('/signals')
    expect(url.searchParams.get('topic')).toBe('3')
    expect(url.searchParams.get('id')).toBe('article-1')
    expect(url.searchParams.get('from')).toBe('/topics?id=3')
  })
  it('preserves source filters and the exact monitor view', () => {
    const from = '/monitor?source=tech:abc&detail=signals&content=high&q=Vercel'
    const url = new URL(
      articleDestination('a', {
        from,
        filters: { sourceRef: 'tech:abc', mode: 'high' },
      }),
      'https://local.test',
    )
    expect(url.searchParams.get('sourceRef')).toBe('tech:abc')
    expect(url.searchParams.get('from')).toBe(safeReturnPath(from))
  })
  it('returns a policy to the filtered list instead of resetting it', () => {
    const from =
      '/policies?search=AI&region=北京&id=one&from=%2Ftopics%3Fid%3D3'
    expect(
      new URL(
        withOrigin('/policies/one', from),
        'https://local.test',
      ).searchParams.get('from'),
    ).toBe(safeReturnPath(from))
    expect(returnLabel(from)).toBe('返回政策列表')
  })
  it('makes saved article scope explicit and returns saved policies to the collection', () => {
    const context = { from: '/saved', filters: { saved: '1' } }
    expect(
      new URL(
        articleDestination('a', context),
        'https://local.test',
      ).searchParams.get('saved'),
    ).toBe('1')
    expect(
      new URL(
        policyDestination('p', context),
        'https://local.test',
      ).searchParams.get('from'),
    ).toBe('/saved')
    expect(returnLabel('/saved')).toBe('返回收藏')
  })
  it('rejects external, malformed and non-reading return destinations', () => {
    for (const path of [
      'https://evil.test',
      '//evil.test',
      '/\\evil.test',
      '/api/reader/signals',
      '/unknown',
      '/topics?' + 'a'.repeat(2100),
      ['/topics'] as unknown as string,
    ])
      expect(safeReturnPath(path)).toBeNull()
    expect(safeReturnPath('/topics?id=3')).toBe('/topics?id=3')
  })
  it('distinguishes historical insights from today using the business timezone', () => {
    expect(
      insightFreshness('2026-09-18T20:00:00Z', '2026-09-19T01:00:00Z'),
    ).toBe('今日生成')
    expect(
      insightFreshness('2026-09-17T00:00:00Z', '2026-09-19T01:00:00Z'),
    ).toBe('历史洞察')
    expect(insightFreshness(null, '2026-09-19T01:00:00Z')).toBe('尚未生成')
  })
})
