import { NextResponse } from 'next/server'
import { readPredictions, readReviews } from '../../../lib/journal-store'
export const dynamic = 'force-dynamic'

// 趋势预测与复核记录。prediction.status: pending / hit / missed 等；
// 复核（reviews）是预测的事后验证。
export async function GET() {
  const headers = { 'Cache-Control': 'no-store' }
  try {
    const [predictions, reviews] = await Promise.all([
      readPredictions(),
      readReviews(),
    ])
    return NextResponse.json({ data: { predictions, reviews } }, { headers })
  } catch {
    return NextResponse.json(
      { error: '趋势预测暂时不可用' },
      { status: 503, headers },
    )
  }
}
