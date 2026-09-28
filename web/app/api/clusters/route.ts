import { NextResponse } from 'next/server'
import { readClusters } from '../../../lib/journal-store'
export const dynamic = 'force-dynamic'

// 信号聚类清单：id 即 /api/reader/signals?topic= 的取值。
export async function GET() {
  const headers = { 'Cache-Control': 'no-store' }
  try {
    return NextResponse.json({ data: await readClusters() }, { headers })
  } catch {
    return NextResponse.json(
      { error: '聚类清单暂时不可用' },
      { status: 503, headers },
    )
  }
}
