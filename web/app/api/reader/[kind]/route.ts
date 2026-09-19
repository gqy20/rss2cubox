import { NextRequest, NextResponse } from 'next/server'
import {
  readSignals,
  readArticle,
  readPolicies,
  readPolicy,
} from '../../../../lib/journal-store'
export const dynamic = 'force-dynamic'
const headers = { 'Cache-Control': 'no-store' }
function failure(error: unknown) {
  const messages: Record<string, string> = {
    'Invalid date': '日期格式应为 YYYY-MM-DD',
    'Invalid cursor': '加载位置已失效，请刷新列表',
    'Invalid topic': '专题编号无效',
    'Invalid source': '信源编号无效',
    'Missing saved selection': '请从当前浏览器的收藏进入',
    'Invalid selection': '收藏列表格式无效',
  }
  const message = error instanceof Error ? messages[error.message] : undefined
  if (!message)
    console.error(
      'Reader request failed',
      error instanceof Error ? error.message : error,
    )
  return NextResponse.json(
    { error: message || '内容暂时无法加载，请稍后重试' },
    { status: message ? 400 : 503, headers },
  )
}
export async function GET(
  request: NextRequest,
  context: { params: Promise<{ kind: string }> },
) {
  const { kind } = await context.params,
    params = request.nextUrl.searchParams
  try {
    if (kind === 'signals')
      return NextResponse.json(await readSignals(params), { headers })
    if (kind === 'policies')
      return NextResponse.json(await readPolicies(params), { headers })
    if (kind === 'article' || kind === 'policy') {
      const id = params.get('id')
      if (!id || id.length > 255)
        return NextResponse.json(
          { error: '请提供有效的内容编号' },
          { status: 400, headers },
        )
      const data =
        kind === 'article' ? await readArticle(id) : await readPolicy(id)
      return NextResponse.json(data ? { data } : { error: '未找到这条内容' }, {
        status: data ? 200 : 404,
        headers,
      })
    }
    return NextResponse.json({ error: '未找到接口' }, { status: 404, headers })
  } catch (error) {
    return failure(error)
  }
}
/** Read-only query over this browser's saved article IDs; IDs do not go into the URL. */
export async function POST(
  request: NextRequest,
  context: { params: Promise<{ kind: string }> },
) {
  const { kind } = await context.params
  if (kind !== 'signals')
    return NextResponse.json(
      { error: '不支持此查询' },
      { status: 405, headers: { ...headers, Allow: 'GET' } },
    )
  try {
    let body: unknown
    try {
      body = await request.json()
    } catch {
      throw new Error('Invalid selection')
    }
    const ids = (body as { ids?: unknown })?.ids
    if (
      !Array.isArray(ids) ||
      ids.length > 5000 ||
      ids.some((id) => typeof id !== 'string' || !id || id.length > 255)
    )
      throw new Error('Invalid selection')
    const params = new URLSearchParams(request.nextUrl.searchParams)
    params.set('saved', '1')
    return NextResponse.json(await readSignals(params, [...new Set(ids)]), {
      headers,
    })
  } catch (error) {
    return failure(error)
  }
}
