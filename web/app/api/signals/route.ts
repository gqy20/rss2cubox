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
} from '../../../lib/icApi'
import { buildArticleSearchWhere, formatLocalArticleRow } from '../../../lib/localArticleRows'

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
  const rawPage = parseInt(searchParams.get('page') || '1', 10)
  const rawLimit = parseInt(searchParams.get('limit') || '50', 10)
  const page = Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1
  const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.min(rawLimit, 100) : 50
  const search = searchParams.get('search')?.trim() || ''
  const date = searchParams.get('date')?.trim() || ''

  if (date && !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return NextResponse.json({ error: 'Invalid date format, expected YYYY-MM-DD' }, { status: 400, headers: NO_STORE_HEADERS })
  }

  const apiSource = process.env.API_SOURCE || 'local'

  if (apiSource === 'local') {
    // Use local PostgreSQL
    const dbUrl = process.env.LOCAL_DB_URL
    if (!dbUrl) {
      return NextResponse.json({ error: 'LOCAL_DB_URL not configured' }, { status: 500, headers: NO_STORE_HEADERS })
    }

    try {
      const client = await pool.connect()
      try {
        const whereParts: string[] = []
        const whereParams: string[] = []
        if (date) {
          whereParams.push(date)
          whereParts.push(`COALESCE(publish_time, created_at) >= $${whereParams.length}::date AND COALESCE(publish_time, created_at) < $${whereParams.length}::date + INTERVAL '1 day'`)
        }

        const searchWhere = buildArticleSearchWhere(search, whereParams.length + 1)
        if (searchWhere) {
          whereParams.push(searchWhere.value)
          whereParts.push(searchWhere.sql)
        }

        const whereSql = whereParts.length ? `WHERE ${whereParts.join(' AND ')}` : ''
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
          LIMIT $${whereParams.length + 1} OFFSET $${whereParams.length + 2}
        `
        const countQuery = `SELECT COUNT(*) FROM articles ${whereSql}`
        const params: (string | number)[] = [...whereParams, limit, (page - 1) * limit]

        const countResult = await client.query(countQuery, whereParams)
        const total = parseInt(countResult.rows[0]?.count || '0', 10)

        const result = await client.query(query, params)
        const articles = result.rows

        const formatted = articles.map(formatLocalArticleRow)

        return NextResponse.json({
          data: formatted,
          total,
          page,
          hasMore: (page - 1) * limit + formatted.length < total,
        }, { headers: NO_STORE_HEADERS })
      } finally {
        client.release()
      }
    } catch (error) {
      console.error('Local DB error:', error)
      return NextResponse.json({ error: 'Failed to fetch from local database' }, { status: 500, headers: NO_STORE_HEADERS })
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
    content_source: e.content_source,
    signal_type: e.signal_type,
    evidence_strength: e.evidence_strength,
    novelty_score: e.novelty_score,
    impact_horizon: e.impact_horizon,
    confidence: e.confidence,
    entities: Array.isArray(e.entities) ? e.entities : [],
    watch_keywords: Array.isArray(e.watch_keywords) ? e.watch_keywords : [],
    prediction: e.prediction,
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
  }, { headers: NO_STORE_HEADERS })
}
