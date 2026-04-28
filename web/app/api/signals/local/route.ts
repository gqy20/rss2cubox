import { NextRequest, NextResponse } from 'next/server'
import { Pool } from 'pg'
import { matchesSearch, matchesDate, sortArticles, normalizeSource } from '../../../../lib/icApi'

const pool = new Pool({
  connectionString: process.env.LOCAL_DB_URL,
})

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
      let query: string
      let countQuery: string
      let params: (string | number)[]

      // Parse composite cursor: "publish_time|id"
      let cursorTime: string | null = null
      let cursorId: string | null = null
      if (cursorParam) {
        const parts = cursorParam.split('|')
        cursorTime = parts[0] || null
        cursorId = parts[1] || null
      }

      if (date) {
        // Date range query with optional cursor
        if (cursorTime && cursorId) {
          query = `
            SELECT id, source_type, source_feed_id, source_feed_name, source_article_id,
                   title, url, pic_url, description, publish_time, tags,
                   importance_score, reason, actionable, hidden_signal,
                   created_at, updated_at
            FROM articles
            WHERE publish_time >= $1::date AND publish_time < $1::date + INTERVAL '1 day'
              AND (publish_time < $2::timestamp OR (publish_time = $2::timestamp AND id < $3))
            ORDER BY publish_time DESC, id DESC
            LIMIT $4
          `
          params = [date, cursorTime, cursorId, limit]
        } else {
          query = `
            SELECT id, source_type, source_feed_id, source_feed_name, source_article_id,
                   title, url, pic_url, description, publish_time, tags,
                   importance_score, reason, actionable, hidden_signal,
                   created_at, updated_at
            FROM articles
            WHERE publish_time >= $1::date AND publish_time < $1::date + INTERVAL '1 day'
            ORDER BY publish_time DESC, id DESC
            LIMIT $2
          `
          params = [date, limit]
        }
        countQuery = `
          SELECT COUNT(*) FROM articles
          WHERE publish_time >= $1::date AND publish_time < $1::date + INTERVAL '1 day'
        `
      } else {
        // No date filter - use composite cursor-based pagination (publish_time + id)
        if (cursorTime && cursorId) {
          query = `
            SELECT id, source_type, source_feed_id, source_feed_name, source_article_id,
                   title, url, pic_url, description, publish_time, tags,
                   importance_score, reason, actionable, hidden_signal,
                   created_at, updated_at
            FROM articles
            WHERE publish_time IS NOT NULL
              AND (publish_time < $1::timestamp OR (publish_time = $1::timestamp AND id < $2))
            ORDER BY publish_time DESC, id DESC
            LIMIT $3
          `
          params = [cursorTime, cursorId, limit]
        } else {
          query = `
            SELECT id, source_type, source_feed_id, source_feed_name, source_article_id,
                   title, url, pic_url, description, publish_time, tags,
                   importance_score, reason, actionable, hidden_signal,
                   created_at, updated_at
            FROM articles
            ORDER BY publish_time DESC, id DESC
            LIMIT $1
          `
          params = [limit]
        }
        countQuery = 'SELECT COUNT(*) FROM articles'
      }

      // Get total count
      const countResult = date
        ? await client.query(countQuery, date ? [date] : [])
        : await client.query(countQuery)
      const total = parseInt(countResult.rows[0]?.count || '0', 10)

      // Get articles
      const result = await client.query(query, params)
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
        actionable: row.actionable || '',
        reason: row.reason || '',
        cover_url: row.pic_url || '',
        source_feed: row.source_feed_id || '',
        source_label: row.source_feed_name || '',
        publish_time: formatTime(row.publish_time),
      }))

      // Apply search filter in memory
      const filtered = formatted.filter(
        (e) => matchesDate({ publish_time: e.time } as any, date) && matchesSearch(e as any, search)
      )
      const sorted = sortArticles(filtered as any)

      // Next cursor: composite of last item's publish_time and id for stable pagination
      const lastItem = sorted.length > 0 ? sorted[sorted.length - 1] : null
      const nextCursor = lastItem ? `${lastItem.publish_time}|${lastItem.id}` : null

      return NextResponse.json({
        data: sorted,
        total,
        cursor: nextCursor,
        hasMore: articles.length === limit,
      })
    } finally {
      client.release()
    }
  } catch (error) {
    console.error('Local DB error:', error)
    return NextResponse.json({ error: 'Failed to fetch from local database' }, { status: 500 })
  }
}
