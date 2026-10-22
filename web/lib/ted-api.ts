import { NextResponse } from 'next/server'
import { TedValidationError } from './ted'
import { TedConflictError } from './ted-store'

export const tedHeaders = { 'Cache-Control': 'private, no-store' }
export function tedError(error: unknown) {
  if (error instanceof TedValidationError)
    return NextResponse.json(
      { error: error.message },
      { status: 400, headers: tedHeaders },
    )
  if (error instanceof TedConflictError)
    return NextResponse.json(
      { error: error.message },
      { status: 409, headers: tedHeaders },
    )
  return NextResponse.json(
    { error: '报告数据暂时不可用，请稍后重试。' },
    { status: 503, headers: tedHeaders },
  )
}
export async function tedBody(request: Request) {
  if (Number(request.headers.get('content-length') || 0) > 2_000_000)
    throw new TedValidationError('报告内容过大，请减少正文或引用数量。')
  const raw = await request.text()
  if (raw.length > 2_000_000) throw new TedValidationError('报告内容过大。')
  try {
    const data = JSON.parse(raw)
    if (!data || typeof data !== 'object' || Array.isArray(data))
      throw new Error()
    return data as Record<string, unknown>
  } catch {
    throw new TedValidationError('请求内容应为 JSON 对象。')
  }
}
