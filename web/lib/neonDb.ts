import { neon } from '@neondatabase/serverless'

function getSql() {
  const url = process.env.NEON_DATABASE_URL
  if (!url) throw new Error('NEON_DATABASE_URL is not configured')
  return neon(url)
}

const DEFAULT_SOURCE_TYPE = process.env.IC_SOURCE_TYPE || 'gqy'
const IC_BATCH_API_URL = process.env.IC_API_URL || ''

function getIcListApiUrl(limit: number, offset: number, sourceType: string = DEFAULT_SOURCE_TYPE): string {
  if (!IC_BATCH_API_URL) throw new Error('IC_API_URL is not configured')
  const baseUrl = IC_BATCH_API_URL.replace(/\/api\/v1\/articles\/batch\/?$/, '')
  const url = new URL('/api/v1/articles', baseUrl)
  url.searchParams.set('limit', String(limit))
  url.searchParams.set('offset', String(offset))
  if (sourceType) url.searchParams.set('source_type', sourceType)
  return url.toString()
}

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

export type EventRow = {
  id: string
  time: string
  source_feed: string
  source_label: string
  source?: string
  cover_url: string
  url: string
  title: string
  status: string
  pushed: boolean
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

export async function loadIcArticles(): Promise<EventRow[]> {
  const batchSize = 100
  const maxPages = 1000
  const items: IcArticle[] = []
  for (let page = 0; page < maxPages; page += 1) {
    const offset = page * batchSize
    const response = await fetch(getIcListApiUrl(batchSize, offset), {
      next: { revalidate: 1800 },
    })
    if (!response.ok) {
      throw new Error(`IC article list request failed: HTTP ${response.status}`)
    }
    const payload = (await response.json()) as IcListResponse
    const chunk = Array.isArray(payload?.data?.list) ? payload.data.list : []
    if (!chunk.length) break
    items.push(...chunk)
    if (chunk.length < batchSize) break
  }
  if (items.length >= batchSize * maxPages) {
    throw new Error(`IC article scan exceeded safety limit (${batchSize * maxPages} rows)`)
  }
  return items.map((data) => {
    return {
      id: String(data.id || ''),
      time: String(data.publish_time || data.created_at || ''),
      source_feed: String(data.source_feed_id || ''),
      source_label: String(data.source_feed_name || ''),
      source: String(data.source_feed_name || ''),
      cover_url: String(data.pic_url || ''),
      url: String(data.url || ''),
      title: String(data.title || ''),
      status: 'exported',
      pushed: true,
      tags: Array.isArray(data.tags) ? data.tags.map((v) => String(v)) : [],
      core_event: String(data.description || ''),
      hidden_signal: String(data.hidden_signal || ''),
      actionable: String(data.actionable || ''),
      reason: String(data.reason || ''),
      exported_at: '',
    } satisfies EventRow
  })
}

export async function loadGlobalInsights(): Promise<GlobalInsights | null> {
  const sql = getSql()
  const rows = await sql`
    SELECT data
    FROM global_insights
    ORDER BY generated_at DESC
    LIMIT 1
  `
  return (rows[0]?.data as GlobalInsights) ?? null
}
