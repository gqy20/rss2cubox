// ── Shared types & data layer for IC article API ──────────────────
// Used by signalStore.ts when API_SOURCE points at the remote IC service.

export type IcArticle = {
  id?: number | string
  title?: string | null
  source_feed_id?: string | null
  source_feed_name?: string | null
  source_type?: string | null
  source_article_id?: string | null
  url?: string | null
  pic_url?: string | null
  description?: string | null
  publish_time?: string | null
  tags?: string[] | null
  reason?: string | null
  actionable?: string | null
  hidden_signal?: string | null
  importance_score?: number | null
  content_source?: string | null
  signal_type?: number | null
  evidence_type?: number | null
  evidence_strength?: number | null
  novelty_score?: number | null
  impact_horizon?: number | null
  audience?: number[] | null
  market_stage?: number | null
  confidence?: number | null
  entities?: string[] | null
  cluster_hint?: string | null
  watch_keywords?: string[] | null
  prediction?: string | null
  disconfirming_evidence?: string | null
  enrich_meta?: Record<string, unknown> | null
  created_at?: string | null
  updated_at?: string | null
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
  importance_score?: number
  content_source?: string
  signal_type?: number
  evidence_strength?: number
  novelty_score?: number
  impact_horizon?: number
  confidence?: number
  entities?: string[]
  watch_keywords?: string[]
  prediction?: string
  actionable: string
  reason: string
  exported_at?: string
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
  // Keep any path prefix on the configured base URL (e.g. https://host/base).
  const root = clean.endsWith('/') ? clean : `${clean}/`
  const url = new URL('api/v1/articles', root)
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
    importance_score: typeof data.importance_score === 'number' ? data.importance_score : undefined,
    content_source: String(data.content_source || ''),
    signal_type: typeof data.signal_type === 'number' ? data.signal_type : undefined,
    evidence_strength: typeof data.evidence_strength === 'number' ? data.evidence_strength : undefined,
    novelty_score: typeof data.novelty_score === 'number' ? data.novelty_score : undefined,
    impact_horizon: typeof data.impact_horizon === 'number' ? data.impact_horizon : undefined,
    confidence: typeof data.confidence === 'number' ? data.confidence : undefined,
    entities: Array.isArray(data.entities) ? data.entities.map((v) => String(v)) : [],
    watch_keywords: Array.isArray(data.watch_keywords) ? data.watch_keywords.map((v) => String(v)) : [],
    prediction: String(data.prediction || ''),
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
    const response = await fetch(buildApiUrl(BATCH_SIZE, offset, baseUrl, sourceType), { cache: 'no-store' })
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
