import { NextRequest, NextResponse } from 'next/server'
import { createSuggestion, listSuggestions } from '../../../lib/suggest-store'
import { publicSourceUrl, UnsafeSourceUrl } from '../../../lib/public-source-fetch'
import { canManageSuggestions, suggestionBody, SuggestionRequestError } from '../../../lib/suggest-request'
export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

const headers = { 'Cache-Control': 'no-store' }
function unauthorized() {
  return NextResponse.json({ error: '需要维护者授权。' }, {
    status: 401, headers: { ...headers, 'WWW-Authenticate': 'Bearer' },
  })
}

// GET：审核视图——全部建议（含体检结果与状态）。
export async function GET(request: NextRequest) {
  if (!canManageSuggestions(request)) return unauthorized()
  try {
    return NextResponse.json({ data: await listSuggestions() }, { headers })
  } catch {
    return NextResponse.json(
      { error: '建议清单暂时不可用' },
      { status: 503, headers },
    )
  }
}

// POST：提交候选信源。Body: {url, name?, kind: tech|policy, note?, submitted_by?}
// 提交即体检（同步，~10s 超时），health 返回判定；是否接入由维护者人工决定。
export async function POST(request: NextRequest) {
  if (!canManageSuggestions(request)) return unauthorized()
  try {
    const body = await suggestionBody(request)
    const url = publicSourceUrl(typeof body.url === 'string' ? body.url.trim() : '').href
    if (body.kind !== undefined && body.kind !== 'tech' && body.kind !== 'policy')
      throw new SuggestionRequestError('信源类型应为 tech 或 policy。')
    const row = await createSuggestion({
      url,
      name: typeof body.name === 'string' ? body.name : '',
      kind: typeof body.kind === 'string' ? body.kind : 'tech',
      note: typeof body.note === 'string' ? body.note : '',
      submitted_by: typeof body.submitted_by === 'string' ? body.submitted_by : '',
    })
    return NextResponse.json({ data: row }, { headers })
  } catch (error) {
    if (error instanceof UnsafeSourceUrl || error instanceof SuggestionRequestError)
      return NextResponse.json({ error: error.message }, {
        status: error instanceof SuggestionRequestError ? error.status : 400, headers,
      })
    console.error('suggest-source failed', error instanceof Error ? error.name : 'unknown_error')
    return NextResponse.json(
      { error: '提交失败，请稍后重试' },
      { status: 503, headers },
    )
  }
}
