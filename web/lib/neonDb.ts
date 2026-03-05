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
  keep?: boolean | null
  status: string
  drop_reason: string
  pushed: boolean
  enriched: boolean
  tags: string[]
  core_event: string
  hidden_signal: string
  actionable: string
  reason: string
  run_id: string
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
    WHERE (data->>'score')::float >= 0.6
       OR (data->>'pushed') = 'true'
    ORDER BY event_time DESC NULLS LAST
    LIMIT 2000
  `
  return rows.map((r) => r.data as EventRow)
}

export async function loadGlobalInsights(): Promise<GlobalInsights | null> {
  const sql = getSql()
  const rows = await sql`SELECT data FROM global_insights WHERE singleton = TRUE LIMIT 1`
  return (rows[0]?.data as GlobalInsights) ?? null
}
