import { NextRequest, NextResponse } from 'next/server'
import { createSuggestion, listSuggestions } from '../../../lib/suggest-store'
export const dynamic = 'force-dynamic'

const headers = { 'Cache-Control': 'no-store' }

// GET：审核视图——全部建议（含体检结果与状态）。
export async function GET() {
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
  let body: Record<string, unknown>
  try {
    body = (await request.json()) as Record<string, unknown>
  } catch {
    return NextResponse.json({ error: '请求体应为 JSON' }, { status: 400, headers })
  }
  const url = typeof body.url === 'string' ? body.url.trim() : ''
  if (!/^https?:\/\/.{4,400}$/.test(url))
    return NextResponse.json(
      { error: '请提供合法的 http(s) 信源地址' },
      { status: 400, headers },
    )
  try {
    const row = await createSuggestion({
      url,
      name: typeof body.name === 'string' ? body.name : '',
      kind: typeof body.kind === 'string' ? body.kind : 'tech',
      note: typeof body.note === 'string' ? body.note : '',
      submitted_by: typeof body.submitted_by === 'string' ? body.submitted_by : '',
    })
    return NextResponse.json({ data: row }, { headers })
  } catch (error) {
    console.error('suggest-source failed', error)
    return NextResponse.json(
      { error: '提交失败，请稍后重试' },
      { status: 503, headers },
    )
  }
}
