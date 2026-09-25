import { createHash } from 'node:crypto'
import { filterKeys, type SearchScope } from './reader-search'

export type ReaderCursor = {
  v: 1
  query: string
  snapshot: string
  rank: number
  time: string
  id: string
}
export function cursorQuery(kind: SearchScope, params: URLSearchParams) {
  // Order is part of the signature; derived from the canonical filterKeys.
  const keys = ['search', ...filterKeys, 'selection']
  const filters = keys.map((key) => [key, (params.get(key) || '').trim()])
  return createHash('sha256')
    .update(JSON.stringify([kind, filters]))
    .digest('hex')
    .slice(0, 24)
}
export function decodeCursor(
  value: string | null,
  query: string,
): ReaderCursor | null {
  if (!value) return null
  try {
    if (value.length > 2048 || !/^[A-Za-z0-9_-]+$/.test(value))
      throw new Error()
    const c = JSON.parse(
      Buffer.from(value, 'base64url').toString('utf8'),
    ) as ReaderCursor
    if (
      c.v !== 1 ||
      c.query !== query ||
      !Number.isInteger(c.rank) ||
      c.rank < 0 ||
      c.rank > 1 ||
      typeof c.id !== 'string' ||
      !c.id ||
      c.id.length > 255
    )
      throw new Error()
    for (const value of [c.snapshot, c.time])
      if (
        typeof value !== 'string' ||
        !/^\d{4}-\d{2}-\d{2}T[\d:.]+Z$/.test(value) ||
        !Number.isFinite(Date.parse(value))
      )
        throw new Error()
    return c
  } catch {
    throw new Error('Invalid cursor')
  }
}
export function encodeCursor(cursor: ReaderCursor) {
  return Buffer.from(JSON.stringify(cursor)).toString('base64url')
}
export function cursorBoundary(
  values: unknown[],
  cursor: ReaderCursor | null,
  rank: string,
  time: string,
) {
  if (!cursor) return ''
  const index = values.length
  values.push(cursor.rank, cursor.time, cursor.id)
  return `((${rank}) > $${index + 1}::int OR ((${rank}) = $${index + 1}::int AND (${time},id) < ($${index + 2}::timestamptz,$${index + 3}::text)))`
}

export function savedFingerprint(ids: string[]) {
  return createHash('sha256')
    .update(JSON.stringify([...new Set(ids)].sort()))
    .digest('hex')
    .slice(0, 24)
}
