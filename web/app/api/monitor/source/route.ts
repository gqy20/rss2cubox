import { NextRequest, NextResponse } from 'next/server'
import { readMonitorDetail } from '../../../../lib/monitor-store'
export const dynamic = 'force-dynamic'
export async function GET(request: NextRequest) {
  const id = request.nextUrl.searchParams.get('id') || ''
  const headers = { 'Cache-Control': 'no-store' }
  if (!/^(tech|policy):[a-f0-9]{32}$/.test(id))
    return NextResponse.json(
      { error: '无效的信源编号' },
      { status: 400, headers },
    )
  try {
    const data = await readMonitorDetail(id)
    return NextResponse.json(data ? { data } : { error: '未找到该信源' }, {
      status: data ? 200 : 404,
      headers,
    })
  } catch {
    return NextResponse.json(
      { error: '信源详情暂时不可用，请重试' },
      { status: 503, headers },
    )
  }
}
