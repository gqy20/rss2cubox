import { NextRequest, NextResponse } from 'next/server'
import { Pool } from 'pg'
import { normalizeSource } from '../../../../lib/icApi'

const pool = new Pool({
  connectionString: process.env.LOCAL_DB_URL,
})

function buildSearchWhere(search: string, paramIndex: number): { sql: string; value: string } | null {
  if (!search) return null
  return {
    sql: `(
      title ILIKE $${paramIndex}
      OR source_feed_name ILIKE $${paramIndex}
      OR source_feed_id ILIKE $${paramIndex}
      OR hidden_signal ILIKE $${paramIndex}
      OR description ILIKE $${paramIndex}
      OR reason ILIKE $${paramIndex}
      OR actionable ILIKE $${paramIndex}
      OR url ILIKE $${paramIndex}
      OR pic_url ILIKE $${paramIndex}
      OR publish_time::text ILIKE $${paramIndex}
      OR tags::text ILIKE $${paramIndex}
    )`,
    value: `%${search}%`,
  }
}

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams
  const rawLimit = parseInt(searchParams.get('limit') || '50', 10)
  const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.min(rawLimit, 100) : 50
  const search = searchParams.get('search')?.trim() || ''
  const date = searchParams.get('date')?.trim() || ''
  // Cursor: "$publish_time|$id" composite string for stable ordering
  const cursorParam = searchParams.get('cursor')?.trim() || null

  if (date && !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return NextResponse.json({ error: 'Invalid date format, expected YYYY-MM-DD' }, { status: 400 })
  }

  const dbUrl = process.env.LOCAL_DB_URL
  if (!dbUrl) {
    return NextResponse.json({ error: 'LOCAL_DB_URL not configured' }, { status: 500 })
  }

  try {
    const client = await pool.connect()
    try {
      // Parse composite cursor: "publish_time|id"
      let cursorTime: string | null = null
      let cursorId: string | null = null
      if (cursorParam) {
        const parts = cursorParam.split('|')
        cursorTime = parts[0] || null
        cursorId = parts[1] || null
      }

      const baseWhereParts: string[] = []
      const baseParams: string[] = []

      if (date) {
        baseParams.push(date)
        baseWhereParts.push(`publish_time >= $${baseParams.length}::date AND publish_time < $${baseParams.length}::date + INTERVAL '1 day'`)
      }

      const searchWhere = buildSearchWhere(search, baseParams.length + 1)
      if (searchWhere) {
        baseParams.push(searchWhere.value)
        baseWhereParts.push(searchWhere.sql)
      }

      const queryWhereParts = [...baseWhereParts]
      const queryParams: (string | number)[] = [...baseParams]
      if (cursorTime && cursorId) {
        queryParams.push(cursorTime, cursorId)
        const timeParam = queryParams.length - 1
        const idParam = queryParams.length
        queryWhereParts.push(`(publish_time < $${timeParam}::timestamp OR (publish_time = $${timeParam}::timestamp AND id < $${idParam}))`)
      }

      const whereSql = queryWhereParts.length ? `WHERE ${queryWhereParts.join(' AND ')}` : ''
      const countWhereSql = baseWhereParts.length ? `WHERE ${baseWhereParts.join(' AND ')}` : ''
      const query = `
        SELECT id, source_type, source_feed_id, source_feed_name, source_article_id,
               title, url, pic_url, description, publish_time, tags,
               importance_score, reason, actionable, hidden_signal,
               created_at, updated_at
        FROM articles
        ${whereSql}
        ORDER BY publish_time DESC NULLS LAST, id DESC
        LIMIT $${queryParams.length + 1}
      `
      const countQuery = `SELECT COUNT(*) FROM articles ${countWhereSql}`
      queryParams.push(limit)

      // Get total count
      const countResult = await client.query(countQuery, baseParams)
      const total = parseInt(countResult.rows[0]?.count || '0', 10)

      // Get articles
      const result = await client.query(query, queryParams)
      const articles = result.rows

      // Format response
      const formatTime = (dt: any): string => {
        if (!dt) return ''
        if (typeof dt === 'string') return dt
        if (typeof dt.toISOString === 'function') return dt.toISOString()
        return String(dt)
      }
      const formatted = articles.map((row) => ({
        id: row.id,
        title: row.title || '',
        url: row.url || '',
        source: normalizeSource({ source_feed_name: row.source_feed_name, source_feed_id: row.source_feed_id, url: row.url } as any),
        time: formatTime(row.publish_time),
        exported: true,
        status: 'exported',
        tags: Array.isArray(row.tags) ? row.tags : [],
        core_event: row.description || '',
        hidden_signal: row.hidden_signal || '',
        importance_score: typeof row.importance_score === 'number' ? row.importance_score : undefined,
        actionable: row.actionable || '',
        reason: row.reason || '',
        cover_url: row.pic_url || '',
        source_feed: row.source_feed_id || '',
        source_label: row.source_feed_name || '',
        publish_time: formatTime(row.publish_time),
      }))

      // Next cursor: composite of last item's publish_time and id for stable pagination
      const lastItem = formatted.length > 0 ? formatted[formatted.length - 1] : null
      const nextCursor = lastItem ? `${lastItem.publish_time}|${lastItem.id}` : null

      return NextResponse.json({
        data: formatted,
        total,
        cursor: nextCursor,
        hasMore: formatted.length === limit,
      })
    } finally {
      client.release()
    }
  } catch (error) {
    console.error('Local DB error:', error)
    return NextResponse.json({ error: 'Failed to fetch from local database' }, { status: 500 })
  }
}
