import { NextResponse } from 'next/server'
import { readInsightHistory } from '../../../lib/journal-store'
export const dynamic = 'force-dynamic'

// 全局洞察历史（最近 30 期）：趋势、弱信号、行动建议。data 结构见 GlobalInsights 类型。
export async function GET() {
  const headers = { 'Cache-Control': 'no-store' }
  try {
    const rows = await readInsightHistory()
    return NextResponse.json({ data: rows }, { headers })
  } catch {
    return NextResponse.json(
      { error: '全局洞察暂时不可用' },
      { status: 503, headers },
    )
  }
}
