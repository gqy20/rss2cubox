import { timingSafeEqual } from 'node:crypto'

export class SuggestionRequestError extends Error {
  constructor(message: string, public status = 400) { super(message) }
}

/** Maintainer API credential. Unset or short credentials disable access. */
export function canManageSuggestions(request: Request): boolean {
  const token = process.env.SOURCE_SUGGEST_TOKEN || ''
  const header = request.headers.get('authorization') || ''
  if (token.length < 32 || token.length > 512 || header.length > 1024) return false
  const expected = Buffer.from(`Bearer ${token}`), supplied = Buffer.from(header)
  return expected.length === supplied.length && timingSafeEqual(expected, supplied)
}

export async function suggestionBody(request: Request): Promise<Record<string, unknown>> {
  const limit = 8192
  if (Number(request.headers.get('content-length') || 0) > limit)
    throw new SuggestionRequestError('提交内容过大。', 413)
  if (!request.body) throw new SuggestionRequestError('请求体应为 JSON 对象。')
  const reader = request.body.getReader()
  const chunks: Uint8Array[] = []
  let size = 0
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      size += value.byteLength
      if (size > limit) {
        await reader.cancel()
        throw new SuggestionRequestError('提交内容过大。', 413)
      }
      chunks.push(value)
    }
  } finally {
    reader.releaseLock()
  }
  try {
    const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw new Error()
    return body
  } catch {
    throw new SuggestionRequestError('请求体应为 JSON 对象。')
  }
}
