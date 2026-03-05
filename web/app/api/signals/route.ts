import { neon } from '@neondatabase/serverless'
import { NextRequest, NextResponse } from 'next/server'

function getSql() {
  const url = process.env.NEON_DATABASE_URL
  if (!url) throw new Error('NEON_DATABASE_URL is not configured')
  return neon(url)
}

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams
  const page = parseInt(searchParams.get('page') || '1')
  const limit = parseInt(searchParams.get('limit') || '50')

  const sql = getSql()

  // 先获取总数
  const countResult = await sql`
    SELECT COUNT(*) as total FROM run_events
    WHERE (data->>'score')::float >= 0.6 OR (data->>'pushed') = 'true'
  `
  const total = Number(countResult[0]?.total || 0)

  // 获取分页数据
  const offset = (page - 1) * limit
  const rows = await sql`
    SELECT data FROM run_events
    WHERE (data->>'score')::float >= 0.6
       OR (data->>'pushed') = 'true'
    ORDER BY event_time DESC NULLS LAST
    LIMIT ${limit}
    OFFSET ${offset}
  `

  const events = rows.map((r) => r.data)

  // 处理数据去重和格式化
  const seen = new Set<string>()
  const deduped: typeof events = []
  for (const e of events) {
    const key = e.id || `${e.url}|${e.time}|${e.title}`
    if (seen.has(key)) continue
    seen.add(key)
    deduped.push(e)
  }

  // 解析来源
  function resolveSource(row: Record<string, unknown>): string {
    const label = String(row.source_label || row.source || '').trim()
    if (label) return label
    const feed = String(row.source_feed || '').trim()
    if (feed) {
      try {
        return new URL('https://x.com' + feed).pathname.split('/')[1] || feed
      } catch {
        return feed
      }
    }
    try {
      return new URL(String(row.url || '')).hostname
    } catch {
      return 'unknown'
    }
  }

  const formatted = deduped.map((e) => ({
    id: e.id,
    title: e.title,
    url: e.url,
    source: resolveSource(e),
    time: e.time,
    score: e.score,
    enriched: e.enriched,
    pushed: e.pushed,
    status: e.status,
    tags: e.tags,
    core_event: e.core_event,
    hidden_signal: e.hidden_signal,
    actionable: e.actionable,
    reason: e.reason,
    cover_url: e.cover_url,
  }))

  return NextResponse.json({
    data: formatted,
    total,
    page,
    hasMore: offset + formatted.length < total,
  })
}
