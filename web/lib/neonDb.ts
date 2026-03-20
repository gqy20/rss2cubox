import { neon } from '@neondatabase/serverless'

function getSql() {
  const url = process.env.NEON_DATABASE_URL
  if (!url) throw new Error('NEON_DATABASE_URL is not configured')
  return neon(url)
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
  score: number
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

export async function loadRunEvents(): Promise<EventRow[]> {
  const sql = getSql()
  const rows = await sql`
    SELECT data FROM run_events
    WHERE ((data->>'score')::float >= 0.6
       OR (data->>'pushed') = 'true')
      AND event_time >= (NOW() - INTERVAL '14 days')
    ORDER BY event_time DESC NULLS LAST
    LIMIT 12000
  `
  return rows.map((r) => r.data as EventRow)
}

export async function loadProcessedItems(): Promise<EventRow[]> {
  const sql = getSql()
  const rows = await sql`
    SELECT data
    FROM processed_items
    WHERE NULLIF(data->>'url', '') IS NOT NULL
    ORDER BY COALESCE(NULLIF(data->>'publish_time', ''), NULLIF(data->>'created_at', '')) DESC
    LIMIT 12000
  `
  return rows.map((r) => {
    const data = r.data as Record<string, unknown>
    return {
      id: String(data.id || ''),
      time: String(data.publish_time || data.created_at || ''),
      source_feed: String(data.source_feed_id || ''),
      source_label: String(data.source_feed_name || ''),
      source: String(data.source_feed_name || ''),
      cover_url: String(data.pic_url || ''),
      url: String(data.url || ''),
      title: String(data.title || ''),
      score: Number(data.score || 0),
      status: Boolean(data.exported) ? 'exported' : 'processed',
      pushed: Boolean(data.exported),
      tags: Array.isArray(data.tags) ? data.tags.map((v) => String(v)) : [],
      core_event: String(data.description || ''),
      hidden_signal: String(data.hidden_signal || ''),
      actionable: String(data.actionable || ''),
      reason: String(data.reason || ''),
      exported_at: String(data.exported_at || ''),
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
