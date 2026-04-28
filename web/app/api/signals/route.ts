import { NextRequest, NextResponse } from 'next/server'
import { Pool } from 'pg'
import {
  fetchAllArticles,
  normalizeArticle,
  normalizeSource,
  normalizeTime,
  matchesSearch,
  matchesDate,
  sortArticles,
  type IcArticle,
} from '../../../lib/icApi'

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
  const rawPage = parseInt(searchParams.get('page') || '1', 10)
  const rawLimit = parseInt(searchParams.get('limit') || '50', 10)
  const page = Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1
  const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.min(rawLimit, 100) : 50
  const search = searchParams.get('search')?.trim() || ''
  const date = searchParams.get('date')?.trim() || ''

  if (date && !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return NextResponse.json({ error: 'Invalid date format, expected YYYY-MM-DD' }, { status: 400 })
  }

  const apiSource = process.env.API_SOURCE || 'ic'

  if (apiSource === 'local') {
    // Use local PostgreSQL
    const dbUrl = process.env.LOCAL_DB_URL
    if (!dbUrl) {
      return NextResponse.json({ error: 'LOCAL_DB_URL not configured' }, { status: 500 })
    }

    try {
      const client = await pool.connect()
      try {
        const whereParts: string[] = []
        const whereParams: string[] = []
        if (date) {
          whereParams.push(date)
          whereParts.push(`publish_time >= $${whereParams.length}::date AND publish_time < $${whereParams.length}::date + INTERVAL '1 day'`)
        }

        const searchWhere = buildSearchWhere(search, whereParams.length + 1)
        if (searchWhere) {
          whereParams.push(searchWhere.value)
          whereParts.push(searchWhere.sql)
        }

        const whereSql = whereParts.length ? `WHERE ${whereParts.join(' AND ')}` : ''
        const query = `
          SELECT id, source_type, source_feed_id, source_feed_name, source_article_id,
                 title, url, pic_url, description, publish_time, tags,
                 importance_score, reason, actionable, hidden_signal,
                 created_at, updated_at
          FROM articles
          ${whereSql}
          ORDER BY publish_time DESC NULLS LAST
          LIMIT $${whereParams.length + 1} OFFSET $${whereParams.length + 2}
        `
        const countQuery = `SELECT COUNT(*) FROM articles ${whereSql}`
        const params: (string | number)[] = [...whereParams, limit, (page - 1) * limit]

        const countResult = await client.query(countQuery, whereParams)
        const total = parseInt(countResult.rows[0]?.count || '0', 10)

        const result = await client.query(query, params)
        const articles = result.rows

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
        }))

        return NextResponse.json({
          data: formatted,
          total,
          page,
          hasMore: (page - 1) * limit + formatted.length < total,
        })
      } finally {
        client.release()
      }
    } catch (error) {
      console.error('Local DB error:', error)
      return NextResponse.json({ error: 'Failed to fetch from local database' }, { status: 500 })
    }
  }

  // Default: use IC API
  const sourceType = process.env.IC_SOURCE_TYPE || 'gqy'
  const baseUrl = process.env.IC_API_URL || ''
  const articles = await fetchAllArticles(baseUrl, sourceType)

  const filtered = articles.filter((article) => matchesDate(article, date) && matchesSearch(article, search))
  const sorted = sortArticles(filtered)

  const offset = (page - 1) * limit
  const pageRows = sorted.slice(offset, offset + limit)
  const formatted = pageRows.map((e) => ({
    id: e.id,
    title: e.title,
    url: e.url,
    source: normalizeSource(e),
    time: normalizeTime(e),
    exported: true,
    status: 'exported',
    tags: Array.isArray(e.tags) ? e.tags : [],
    core_event: e.description,
    hidden_signal: e.hidden_signal,
    importance_score: e.importance_score,
    actionable: e.actionable,
    reason: e.reason,
    cover_url: e.pic_url,
    source_feed: e.source_feed_id,
    source_label: e.source_feed_name,
  }))

  return NextResponse.json({
    data: formatted,
    total: filtered.length,
    page,
    hasMore: offset + formatted.length < filtered.length,
  })
}
