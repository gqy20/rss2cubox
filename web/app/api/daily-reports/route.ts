import { NextRequest, NextResponse } from 'next/server'
import { readDailyReports } from '../../../lib/journal-store'
export const dynamic = 'force-dynamic'

// 日报归档：每天一份的综合分析（summary/key_topics/trends/top_articles/
// weak_signals/daily_advices/cluster_evolution/prediction_status/confidence_level）。
// 不带参数返回全部（倒序）；?date=YYYY-MM-DD 取单份。
export async function GET(request: NextRequest) {
  const headers = { 'Cache-Control': 'no-store' }
  const date = request.nextUrl.searchParams.get('date') || ''
  if (date && !/^\d{4}-\d{2}-\d{2}$/.test(date))
    return NextResponse.json(
      { error: '日期格式应为 YYYY-MM-DD' },
      { status: 400, headers },
    )
  try {
    const rows = await readDailyReports(date)
    return NextResponse.json({ data: rows }, { headers })
  } catch {
    return NextResponse.json(
      { error: '日报归档暂时不可用' },
      { status: 503, headers },
    )
  }
}
