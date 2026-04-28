// ── Shared types & data layer for IC article API ──────────────────
// Unifies the duplicated logic between signalStore.ts and api/signals/route.ts

export type IcArticle = {
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

export type IcListResponse = {
  ok?: boolean
  data?: {
    list?: IcArticle[]
    limit?: number
    offset?: number
  }
}

export type EventRow = {
  id: string
  time: string
  source_feed: string
  source_label: string
  source: string
  cover_url: string
  url: string
  title: string
  status: string
  exported: boolean
  tags: string[]
  core_event: string
  hidden_signal: string
  actionable: string
  reason: string
  exported_at?: string
}

export type GlobalInsights = {
  generated_at?: string
  source_count?: number
  trends?: string[]
  weak_signals?: string[]
  daily_advices?: string[]
}

const BATCH_SIZE = 100
const MAX_PAGES = 1000

export function buildApiUrl(
  limit: number,
  offset: number,
  baseUrl: string,
  sourceType: string = 'gqy',
): string {
  if (!baseUrl) return ''
  const clean = baseUrl.replace(/\/api\/v1\/articles\/batch\/?$/, '')
  const url = new URL('/api/v1/articles', clean)
  url.searchParams.set('limit', String(limit))
  url.searchParams.set('offset', String(offset))
  if (sourceType) url.searchParams.set('source_type', sourceType)
  return url.toString()
}

export function normalizeSource(article: IcArticle): string {
  const label = String(article.source_feed_name || '').trim()
  if (label) return label
  const feed = String(article.source_feed_id || '').trim()
  if (feed) {
    try { return new URL(feed).hostname } catch { return feed }
  }
  try { return new URL(String(article.url || '')).hostname } catch { return 'unknown' }
}

export function normalizeTime(article: IcArticle): string {
  return String(article.publish_time || article.created_at || '')
}

export function matchesSearch(article: IcArticle, search: string): boolean {
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
  if (fields.some((v) => String(v || '').toLowerCase().includes(needle))) return true
  return Array.isArray(article.tags) && article.tags.some((tag) => String(tag).toLowerCase().includes(needle))
}

export function matchesDate(article: IcArticle, date: string): boolean {
  if (!date) return true
  // Use a simple date key extraction (YYYY-MM-DD portion)
  const time = normalizeTime(article)
  return time.startsWith(date)
}

export function sortArticles(articles: IcArticle[]): IcArticle[] {
  return [...articles].sort((a, b) => {
    const ta = new Date(normalizeTime(a) || 0).getTime() || 0
    const tb = new Date(normalizeTime(b) || 0).getTime() || 0
    return tb - ta
  })
}

export function normalizeArticle(data: IcArticle): EventRow {
  return {
    id: String(data.id || ''),
    time: normalizeTime(data),
    source_feed: String(data.source_feed_id || ''),
    source_label: String(data.source_feed_name || ''),
    source: String(data.source_feed_name || ''),
    cover_url: String(data.pic_url || ''),
    url: String(data.url || ''),
    title: String(data.title || ''),
    status: 'exported',
    exported: true,
    tags: Array.isArray(data.tags) ? data.tags.map((v) => String(v)) : [],
    core_event: String(data.description || ''),
    hidden_signal: String(data.hidden_signal || ''),
    actionable: String(data.actionable || ''),
    reason: String(data.reason || ''),
    exported_at: '',
  }
}

export async function fetchAllArticles(
  baseUrl: string,
  sourceType: string = 'gqy',
): Promise<IcArticle[]> {
  if (!baseUrl) return []
  const items: IcArticle[] = []
  for (let page = 0; page < MAX_PAGES; page++) {
    const offset = page * BATCH_SIZE
    const response = await fetch(buildApiUrl(BATCH_SIZE, offset, baseUrl, sourceType), {
      next: { revalidate: 1800 },
    })
    if (!response.ok) {
      throw new Error(`IC article list request failed: HTTP ${response.status}`)
    }
    const payload = (await response.json()) as IcListResponse
    const chunk = Array.isArray(payload?.data?.list) ? payload.data.list : []
    if (!chunk.length) break
    items.push(...chunk)
    if (chunk.length < BATCH_SIZE) break
  }
  if (items.length >= BATCH_SIZE * MAX_PAGES) {
    throw new Error(`IC article scan exceeded safety limit (${BATCH_SIZE * MAX_PAGES} rows)`)
  }
  return items
}
