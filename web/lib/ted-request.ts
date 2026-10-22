import { timingSafeEqual } from 'node:crypto'
import type { NextRequest } from 'next/server'

/** Explicit origins prevent cross-site browser writes. */
export function sameOrigin(request: NextRequest) {
  const origin = request.headers.get('origin')
  try {
    return Boolean(
      origin &&
        new URL(origin).host === request.headers.get('host') &&
        new URL(origin).protocol === request.nextUrl.protocol,
    )
  } catch {
    return false
  }
}

/** Background generation credentials stay on the server; readers never sign in. */
export function canWriteTed(request: NextRequest) {
  if (!sameOrigin(request)) return false
  const expected = process.env.TED_WRITE_TOKEN || ''
  const supplied = request.headers.get('authorization') || ''
  if (expected.length < 32 || supplied.length > 1024) return false
  const actual = Buffer.from(supplied), required = Buffer.from(`Bearer ${expected}`)
  return actual.length === required.length && timingSafeEqual(actual, required)
}
