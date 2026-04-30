import { NextRequest, NextResponse } from 'next/server'
import { Pool } from 'pg'
import { buildArticleSearchWhere, formatLocalArticleRow } from '../../../../lib/localArticleRows'

export const dynamic = 'force-dynamic'
export const revalidate = 0

const pool = new Pool({
  connectionString: process.env.LOCAL_DB_URL,
})

const NO_STORE_HEADERS = {
  'Cache-Control': 'no-store, no-cache, must-revalidate, proxy-revalidate',
  Pragma: 'no-cache',
  Expires: '0',
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
    return NextResponse.json({ error: 'Invalid date format, expected YYYY-MM-DD' }, { status: 400, headers: NO_STORE_HEADERS })
  }

  const dbUrl = process.env.LOCAL_DB_URL
  if (!dbUrl) {
    return NextResponse.json({ error: 'LOCAL_DB_URL not configured' }, { status: 500, headers: NO_STORE_HEADERS })
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
        baseWhereParts.push(`COALESCE(publish_time, created_at) >= $${baseParams.length}::date AND COALESCE(publish_time, created_at) < $${baseParams.length}::date + INTERVAL '1 day'`)
      }

      const searchWhere = buildArticleSearchWhere(search, baseParams.length + 1)
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
        queryWhereParts.push(`(COALESCE(publish_time, created_at) < $${timeParam}::timestamp OR (COALESCE(publish_time, created_at) = $${timeParam}::timestamp AND id < $${idParam}))`)
      }

      const whereSql = queryWhereParts.length ? `WHERE ${queryWhereParts.join(' AND ')}` : ''
      const countWhereSql = baseWhereParts.length ? `WHERE ${baseWhereParts.join(' AND ')}` : ''
      const query = `
        SELECT id, source_type, source_feed_id, source_feed_name, source_article_id,
               title, url, pic_url, description, publish_time, tags,
               importance_score, reason, actionable, hidden_signal,
               content_source, signal_type, evidence_strength, novelty_score,
               impact_horizon, confidence, entities, watch_keywords, prediction,
               to_char(COALESCE(publish_time, created_at), 'YYYY-MM-DD"T"HH24:MI:SS.MS') AS display_time,
               created_at, updated_at
        FROM articles
        ${whereSql}
        ORDER BY COALESCE(publish_time, created_at) DESC NULLS LAST, id DESC
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

      const formatted = articles.map((row) => ({
        ...formatLocalArticleRow(row),
        publish_time: row.display_time || '',
      }))

      // Next cursor: composite of last item's publish_time and id for stable pagination
      const lastItem = formatted.length > 0 ? formatted[formatted.length - 1] : null
      const nextCursor = lastItem ? `${lastItem.publish_time}|${lastItem.id}` : null

      return NextResponse.json({
        data: formatted,
        total,
        cursor: nextCursor,
        hasMore: formatted.length === limit,
      }, { headers: NO_STORE_HEADERS })
    } finally {
      client.release()
    }
  } catch (error) {
    console.error('Local DB error:', error)
    return NextResponse.json({ error: 'Failed to fetch from local database' }, { status: 500, headers: NO_STORE_HEADERS })
  }
}
