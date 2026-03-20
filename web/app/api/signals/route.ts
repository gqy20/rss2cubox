import { NextRequest, NextResponse } from 'next/server'
import { getBusinessDayKey, parseBusinessDate } from '../../../lib/time'

const DEFAULT_SOURCE_TYPE = process.env.IC_SOURCE_TYPE || 'gqy'
const IC_BATCH_API_URL = process.env.IC_API_URL || ''

type IcArticle = {
  id: number | string
  title?: string | null
  source_feed_id?: string | null
  source_feed_name?: string | null
  url?: string | null
  pic_url?: string | null
  description?: string | null
  publish_time?: string | null
  tags?: string[] | null
  reason?: string | null
  actionable?: string | null
  hidden_signal?: string | null
  created_at?: string | null
}

type IcListResponse = {
  ok?: boolean
  data?: {
    list?: IcArticle[]
    limit?: number
    offset?: number
  }
}

function buildIcListApiUrl(limit: number, offset: number, sourceType: string = DEFAULT_SOURCE_TYPE): string {
  if (!IC_BATCH_API_URL) throw new Error('IC_API_URL is not configured')
  const baseUrl = IC_BATCH_API_URL.replace(/\/api\/v1\/articles\/batch\/?$/, '')
  const url = new URL('/api/v1/articles', baseUrl)
  url.searchParams.set('limit', String(limit))
  url.searchParams.set('offset', String(offset))
  if (sourceType) url.searchParams.set('source_type', sourceType)
  return url.toString()
}

function normalizeTime(article: IcArticle): string {
  return String(article.publish_time || article.created_at || '')
}

function normalizeSource(article: IcArticle): string {
  const label = String(article.source_feed_name || '').trim()
  if (label) return label
  const feed = String(article.source_feed_id || '').trim()
  if (feed) {
    try {
      return new URL(feed).hostname
    } catch {
      return feed
    }
  }
  try {
    return new URL(String(article.url || '')).hostname
  } catch {
    return 'unknown'
  }
}

function getDateKey(raw: string): string {
  return getBusinessDayKey(raw)
}

function matchesSearch(article: IcArticle, search: string): boolean {
  if (!search) return true
  const needle = search.toLowerCase()
  const fields = [
    article.title,
    article.source_feed_name,
    article.source_feed_id,
    article.hidden_signal,
    article.description,
    article.reason,
    article.actionable,
    article.url,
    article.pic_url,
    article.publish_time,
  ]
  if (fields.some((value) => String(value || '').toLowerCase().includes(needle))) return true
  return Array.isArray(article.tags) && article.tags.some((tag) => String(tag).toLowerCase().includes(needle))
}

function matchesDate(article: IcArticle, date: string): boolean {
  if (!date) return true
  return getDateKey(normalizeTime(article)) === date
}

async function fetchIcArticles(limit: number, offset: number): Promise<IcArticle[]> {
  const response = await fetch(buildIcListApiUrl(limit, offset), {
    next: { revalidate: 1800 },
  })
  if (!response.ok) {
    throw new Error(`IC article list request failed: HTTP ${response.status}`)
  }
  const payload = (await response.json()) as IcListResponse
  return Array.isArray(payload?.data?.list) ? payload.data.list : []
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

  const batchSize = 100
  const maxPages = 1000
  const articles: IcArticle[] = []
  for (let pageIndex = 0; pageIndex < maxPages; pageIndex += 1) {
    const offset = pageIndex * batchSize
    const chunk = await fetchIcArticles(batchSize, offset)
    if (!chunk.length) break
    articles.push(...chunk)
    if (chunk.length < batchSize) break
  }
  if (articles.length >= batchSize * maxPages) {
    throw new Error(`IC article scan exceeded safety limit (${batchSize * maxPages} rows)`)
  }

  const filtered = articles.filter((article) => matchesDate(article, date) && matchesSearch(article, search))
  filtered.sort((a, b) => parseBusinessDate(normalizeTime(b)).getTime() - parseBusinessDate(normalizeTime(a)).getTime())

  const offset = (page - 1) * limit
  const pageRows = filtered.slice(offset, offset + limit)
  const formatted = pageRows.map((e) => ({
    id: e.id,
    title: e.title,
    url: e.url,
    source: normalizeSource(e),
    time: normalizeTime(e),
    pushed: true,
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
