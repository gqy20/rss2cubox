import { neon } from '@neondatabase/serverless'
import { NextRequest, NextResponse } from 'next/server'

const BUSINESS_TZ = 'Asia/Shanghai'

function getSql() {
  const url = process.env.NEON_DATABASE_URL
  if (!url) throw new Error('NEON_DATABASE_URL is not configured')
  return neon(url)
}

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams
  const rawPage = parseInt(searchParams.get('page') || '1', 10)
  const rawLimit = parseInt(searchParams.get('limit') || '50', 10)
  const page = Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1
  const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.min(rawLimit, 100) : 50
  const search = searchParams.get('search')?.trim() || ''
  const date = searchParams.get('date')?.trim() || ''

  if (date && !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return NextResponse.json({ error: 'Invalid date format, expected YYYY-MM-DD' }, { status: 400 })
  }

  const sql = getSql()

  const whereClauses: string[] = ["((data->>'score')::float >= 0.6 OR (data->>'pushed') = 'true')"]
  const params: Array<string | number> = []

  if (date) {
    params.push(date)
    whereClauses.push(`(
      NULLIF(data->>'time', '') IS NOT NULL
      AND data->>'time' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T'
      AND DATE((data->>'time')::timestamptz AT TIME ZONE '${BUSINESS_TZ}') = $${params.length}
    )`)
  }

  if (search) {
    params.push(`%${search}%`)
    const patternIdx = params.length
    whereClauses.push(`(data->>'title' ILIKE $${patternIdx}
      OR data->>'source' ILIKE $${patternIdx}
      OR data->>'source_label' ILIKE $${patternIdx}
      OR data->>'source_feed' ILIKE $${patternIdx}
      OR data->>'hidden_signal' ILIKE $${patternIdx}
      OR data->>'core_event' ILIKE $${patternIdx}
      OR data->>'reason' ILIKE $${patternIdx}
      OR data->>'actionable' ILIKE $${patternIdx}
      OR data->>'url' ILIKE $${patternIdx}
      OR data->>'status' ILIKE $${patternIdx}
      OR data->>'cover_url' ILIKE $${patternIdx}
      OR data->>'time' ILIKE $${patternIdx}
      OR EXISTS (
        SELECT 1
        FROM jsonb_array_elements_text(COALESCE(data->'tags', '[]'::jsonb)) AS tag
        WHERE tag ILIKE $${patternIdx}
      ))`)
  }

  const whereClause = whereClauses.join(' AND ')
  const offset = (page - 1) * limit

  const countSql = `SELECT COUNT(*) as total FROM run_events WHERE ${whereClause}`
  const dataSql = `SELECT data FROM run_events WHERE ${whereClause} ORDER BY event_time DESC NULLS LAST LIMIT $${params.length + 1} OFFSET $${params.length + 2}`

  const countResult = await sql.query(countSql, params) as any
  const total = Number(countResult[0]?.total || 0)

  const rowsResult = await sql.query(dataSql, [...params, limit, offset]) as any
  const events = rowsResult.map((r: any) => r.data)

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

  const formatted = deduped.map((e: any) => ({
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
    hasMore: (page - 1) * limit + formatted.length < total,
  })
}
