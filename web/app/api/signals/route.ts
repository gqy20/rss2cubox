import { NextRequest, NextResponse } from 'next/server'
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
