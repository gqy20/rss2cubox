import { NextRequest, NextResponse } from 'next/server'
import {
  readSignals,
  readArticle,
  readPolicies,
  readPolicy,
} from '../../../../lib/journal-store'

export const dynamic = 'force-dynamic'
export async function GET(
  request: NextRequest,
  context: { params: Promise<{ kind: string }> },
) {
  const { kind } = await context.params
  const params = request.nextUrl.searchParams
  const headers = { 'Cache-Control': 'no-store' }
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
  } catch (e) {
    const invalid =
      e instanceof Error &&
      ['Invalid date', 'Invalid cursor'].includes(e.message)
    console.error('Reader request failed', e instanceof Error ? e.message : e)
    return NextResponse.json(
      {
        error: invalid
          ? e instanceof Error && e.message === 'Invalid cursor'
            ? '加载位置已失效，请刷新列表'
            : '日期格式应为 YYYY-MM-DD'
          : '内容暂时无法加载，请稍后重试',
      },
      { status: invalid ? 400 : 503, headers },
    )
  }
}
