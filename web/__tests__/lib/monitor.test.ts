import { describe, it, expect } from 'vitest'
import {
  needsAttention,
  isStale,
  attentionOrder,
  parseFeedRegistry,
  parsePolicyRegistry,
  errorCategory,
  redactAddress,
  redactError,
  runStreak,
  successShare,
  compareSourceNames,
} from '../../lib/monitor-utils'
import type { MonitorSource, SourceRun } from '../../lib/monitor-types'
const now = Date.parse('2026-09-19T12:00:00Z')
const source = (extra: Partial<MonitorSource> = {}): MonitorSource => ({
  id: 'a',
  kind: 'tech',
  name: 'A',
  domain: 'a.example',
  address: 'https://a.example/feed',
  configuration: 'enabled',
  status: 'ok',
  runs: [],
  lastRun: '2026-09-19T11:00:00Z',
  lastSuccess: '2026-09-19T11:00:00Z',
  lastPublished: '2025-01-01T00:00:00Z',
  failureStreak: 0,
  emptyStreak: 0,
  recovered: false,
  articles: 10,
  analyzed: 5,
  scored: 8,
  high: 3,
  contentAvailable: true,
  ...extra,
})
const run = (status: SourceRun['status']): SourceRun => ({
  id: status,
  at: '2026-09-19T11:00:00Z',
  status,
  fetched: 0,
  durationMs: 10,
  attempts: 1,
  error: null,
})
describe('source health semantics', () => {
  it('does not confuse a slow publishing schedule with a stale poll', () => {
    expect(isStale(source(), now, 24)).toBe(false)
    expect(needsAttention(source(), now, 24)).toBe(false)
  })
  it('excludes explicitly disabled and historical sources from the attention queue', () => {
    for (const configuration of ['disabled', 'historical'] as const)
      expect(
        needsAttention(
          source({
            configuration,
            status: 'failed',
            lastRun: '2026-09-01T00:00:00Z',
          }),
          now,
          24,
        ),
      ).toBe(false)
  })
  it('treats empty and skipped as non-failures, but surfaces repeated empty runs', () => {
    expect(
      needsAttention(source({ status: 'empty', emptyStreak: 1 }), now, 24),
    ).toBe(false)
    expect(needsAttention(source({ status: 'skipped' }), now, 24)).toBe(false)
    expect(
      needsAttention(source({ status: 'empty', emptyStreak: 3 }), now, 24),
    ).toBe(true)
  })
  it('uses the chosen inactivity threshold and keeps failures first', () => {
    const stale = source({ lastRun: '2026-09-18T00:00:00Z' })
    expect(isStale(stale, now, 24)).toBe(true)
    expect(isStale(stale, now, 48)).toBe(false)
    expect(attentionOrder(source({ status: 'failed' }), now, 24)).toBeLessThan(
      attentionOrder(stale, now, 24),
    )
  })
  it('counts consecutive rounds, not every failure in history', () =>
    expect(
      runStreak(
        [run('failed'), run('failed'), run('ok'), run('failed')],
        'failed',
      ),
    ).toBe(2))
  it('excludes skipped rounds and accepts valid empty responses in parsing availability', () =>
    expect(
      successShare([run('ok'), run('empty'), run('skipped'), run('failed')]),
    ).toEqual({ successful: 2, total: 3 }))
})
describe('registry metadata and diagnostic safety', () => {
  it('keeps names and disabled buckets consistent with backend feed definitions', () => {
    const result = parseFeedRegistry(
      '[rsshub]\n5\t/hackernews # Hacker News\n2\t/twitter/user/a # Account\n2\t/bilibili/user/video-browser/3 # Video\n[direct]\nhttps://example.org/feed # Example\n[werss]\n/feed/abc # WeChat',
      'twitter,bilibili,werss',
    )
    expect(result.map((r) => [r.name, r.enabled])).toEqual([
      ['Hacker News', true],
      ['Account', false],
      ['Video', false],
      ['Example', true],
      ['WeChat', false],
    ])
  })
  it('reads policy names and explicit disabled settings without inventing a history', () => {
    const result = parsePolicyRegistry(
      '[[sites]]\nkey="one"\nname="某市政策"\nlist_url="https://example.org/policy"\nregion="某市"\nenabled=false # pending adapter\n',
    )
    expect(result).toEqual([
      {
        kind: 'policy',
        key: 'one',
        name: '某市政策',
        url: 'https://example.org/policy',
        enabled: false,
        region: '某市',
      },
    ])
  })
  it('classifies common failure causes', () => {
    expect(errorCategory('404 Client Error')).toBe('HTTP 404')
    expect(errorCategory('Read timed out')).toBe('超时')
    expect(errorCategory('invalid feed parse: SAXParseException')).toBe(
      '解析错误',
    )
  })
  it('does not mistake ports or URL path numbers for HTTP responses', () => {
    expect(
      errorCategory(
        "HTTPSConnectionPool(host='example.org', port=443): Read timed out",
      ),
    ).toBe('超时')
    expect(
      errorCategory('Connection error for https://example.org:443/feed/404'),
    ).toBe('连接错误')
    expect(errorCategory('HTTP/1.1 503 Service Unavailable')).toBe('HTTP 503')
    expect(errorCategory('status_code=429')).toBe('HTTP 429')
  })
  it('has stable source ordering independent of the runtime locale', () => {
    const rows = [
      { id: 'b', name: '中文' },
      { id: 'c', name: 'Alpha' },
      { id: 'a', name: 'alpha' },
    ]
    expect(rows.sort(compareSourceNames).map((r) => r.id)).toEqual([
      'a',
      'c',
      'b',
    ])
  })
  it('removes embedded credentials and sensitive query values from diagnostics', () => {
    const redacted = redactAddress(
      'https://user:pass@example.org/feed?token=secret&channel_id=public',
    )
    expect(redacted).not.toContain('secret')
    expect(redacted).not.toContain('pass')
    expect(redacted).toContain('channel_id=public')
    expect(
      redactError('Failed https://user:pass@example.org/feed?api_key=secret'),
    ).not.toContain('secret')
  })
})
