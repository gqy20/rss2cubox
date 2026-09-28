import { NextResponse } from 'next/server'
import { readMonitorSnapshot } from '../../../lib/monitor-store'
export const dynamic = 'force-dynamic'

// 信源清单：编号(id)即 /api/monitor/source 的入参，解决"编号只能从页面来"的自助发现问题。
// 精简字段；运行历史明细走 monitor/source。
export async function GET() {
  const headers = { 'Cache-Control': 'no-store' }
  try {
    const snapshot = await readMonitorSnapshot()
    return NextResponse.json(
      {
        data: snapshot.sources.map((s) => ({
          id: s.id,
          name: s.name,
          kind: s.kind,
          configuration: s.configuration,
          status: s.status,
          lastSuccess: s.lastSuccess,
          lastPublished: s.lastPublished,
          failureStreak: s.failureStreak,
          articles: s.articles,
          analyzed: s.analyzed,
          high: s.high,
          region: s.region ?? null,
        })),
        issues: snapshot.issues,
        loadedAt: snapshot.loadedAt,
      },
      { headers },
    )
  } catch {
    return NextResponse.json(
      { error: '信源清单暂时不可用，请稍后重试' },
      { status: 503, headers },
    )
  }
}
