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
  const search = searchParams.get('search')?.trim() || ''
  const date = searchParams.get('date')?.trim() || ''

  const sql = getSql()

  // 基础条件
  const baseCondition = "(data->>'score')::float >= 0.6 OR (data->>'pushed') = 'true'"
  
  // 日期条件：使用北京时间筛选
  let dateCondition = ''
  if (date) {
    // 转换为北京时间日期范围
    dateCondition = `AND DATE(data->>'time'::timestamptz AT TIME ZONE 'Asia/Shanghai') = '${date}'`
  }
  
  let whereClause = baseCondition + dateCondition

  if (search) {
    const escaped = search.replace(/'/g, "''")
    const pattern = `%${escaped}%`
    const searchCondition = `(data->>'title' ILIKE '${pattern}' 
      OR data->>'source' ILIKE '${pattern}'
      OR data->>'source_label' ILIKE '${pattern}'
      OR data->>'hidden_signal' ILIKE '${pattern}'
      OR data->>'core_event' ILIKE '${pattern}'
      OR data->>'reason' ILIKE '${pattern}'
      OR data->>'actionable' ILIKE '${pattern}'
      OR data->>'url' ILIKE '${pattern}')`
    whereClause = `(${baseCondition}) AND ${searchCondition}${dateCondition}`
  }

  // 构建 SQL 查询
  const countSql = `SELECT COUNT(*) as total FROM run_events WHERE ${whereClause}`
  const dataSql = `SELECT data FROM run_events WHERE ${whereClause} ORDER BY event_time DESC NULLS LAST LIMIT ${limit} OFFSET ${(page - 1) * limit}`

  const countResult = await sql.query(countSql) as any
  const total = countResult[0]?.total || 0

  const rowsResult = await sql.query(dataSql) as any
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
