import { describe, it, expect } from 'vitest'
import {
  cursorQuery,
  decodeCursor,
  encodeCursor,
  cursorBoundary,
} from '../../lib/reader-cursor'
const params = new URLSearchParams('search=AI&mode=high')
const signature = cursorQuery('signals', params)
const value = {
  v: 1 as const,
  query: signature,
  snapshot: '2026-09-19T04:00:00.000Z',
  rank: 0,
  time: '2026-09-18T04:32:01.123456Z',
  id: 'last-id',
}
describe('stable reading cursor', () => {
  it('round trips microseconds and the original snapshot', () =>
    expect(decodeCursor(encodeCursor(value), signature)).toEqual(value))
  it('cannot reuse an article cursor with changed filters or in policies', () => {
    expect(() =>
      decodeCursor(encodeCursor(value), cursorQuery('policies', params)),
    ).toThrow('Invalid cursor')
    expect(() =>
      decodeCursor(
        encodeCursor(value),
        cursorQuery('signals', new URLSearchParams('search=other')),
      ),
    ).toThrow('Invalid cursor')
  })
  it('ignores page, record selection and cursor transport when identifying the query', () =>
    expect(
      cursorQuery(
        'signals',
        new URLSearchParams('search=AI&mode=high&id=x&page=3&cursor=abc'),
      ),
    ).toBe(signature))
  it('rejects malformed and out-of-range cursor values', () => {
    for (const c of [
      'garbage',
      encodeCursor({ ...value, rank: 9 }),
      encodeCursor({ ...value, time: 'not-a-date' }),
      encodeCursor({ ...value, id: '' }),
    ])
      expect(() => decodeCursor(c, signature)).toThrow('Invalid cursor')
  })
  it('uses relevance followed by timestamp and id as the continuation boundary', () => {
    const values: unknown[] = ['%AI%', 'ai', value.snapshot]
    const sql = cursorBoundary(
      values,
      value,
      'CASE WHEN title ILIKE $1 THEN 0 ELSE 1 END',
      'publish_time',
    )
    expect(values).toEqual([
      '%AI%',
      'ai',
      value.snapshot,
      0,
      value.time,
      'last-id',
    ])
    expect(sql).toContain('> $4::int')
    expect(sql).toContain('(publish_time,id) < ($5::timestamptz,$6::text)')
  })
})
