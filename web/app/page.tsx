import { readFile } from 'node:fs/promises'
import path from 'node:path'
import DashboardClient from './DashboardClient'
import { loadGlobalInsights, loadRunEvents } from '../lib/neonDb'

export const dynamic = 'force-dynamic'

type GlobalInsights = {
  generated_at?: string
  source_count?: number
  trends?: string[]
  weak_signals?: string[]
  daily_advices?: string[]
}

type Row = {
  id: string
  title: string
  url: string
  source: string
  time: string
  score?: number
  enriched?: boolean
  pushed?: boolean
  status?: string
  tags?: string[]
  core_event?: string
  hidden_signal?: string
  actionable?: string
  reason?: string
  cover_url?: string
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((v) => String(v)).filter((v) => v.trim().length > 0)
}

function dedupeRows(rows: Row[]): Row[] {
  const seen = new Set<string>()
  const out: Row[] = []
  for (const row of rows) {
    const key = row.id || `${row.url}|${row.time}|${row.title}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push(row)
  }
  return out
}

function resolveSource(row: Record<string, unknown>): string {
  const label = String(row.source_label || row.source || '').trim()
  if (label) return label
  const feed = String(row.source_feed || '').trim()
  if (feed) {
    try { return new URL('https://x.com' + feed).pathname.split('/')[1] || feed } catch { return feed }
  }
  try { return new URL(String(row.url || '')).hostname } catch { return 'unknown' }
}

function buildMetrics(rows: Row[]) {
  const sourceCount: Record<string, number> = {}
  for (const r of rows) sourceCount[r.source] = (sourceCount[r.source] ?? 0) + 1
  const topSources = Object.entries(sourceCount)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([source, count]) => ({ source, count }))
  return {
    generated_at: new Date().toISOString(),
    updates_total: rows.length,
    pushed_total: rows.filter((r) => r.pushed).length,
    sources_total: Object.keys(sourceCount).length,
    top_sources: topSources,
  }
}

async function loadFromDb(): Promise<{
  rows: Row[]
  metrics: ReturnType<typeof buildMetrics>
  insights: GlobalInsights | null
}> {
  const [events, rawInsights] = await Promise.all([loadRunEvents(), loadGlobalInsights()])
  const rows: Row[] = dedupeRows(
    events.map((e) => ({
      id: e.id,
      title: e.title,
      url: e.url,
      source: resolveSource(e as unknown as Record<string, unknown>),
      time: e.time,
      score: e.score,
      enriched: e.enriched,
      pushed: e.pushed,
      status: e.status,
      tags: e.tags,
      core_event: e.core_event,
      hidden_signal: e.hidden_signal,
      actionable: e.actionable,
      reason: e.reason,
      cover_url: e.cover_url,
    })),
  )
  const insights = rawInsights
    ? {
        generated_at: rawInsights.generated_at,
        source_count: rawInsights.source_count,
        trends: asStringArray(rawInsights.trends),
        weak_signals: asStringArray(rawInsights.weak_signals),
        daily_advices: asStringArray(rawInsights.daily_advices),
      }
    : null
  return { rows, metrics: buildMetrics(rows), insights }
}

async function loadFromFiles(): Promise<{
  rows: Row[]
  metrics: {
    generated_at?: string
    updates_total?: number
    sources_total?: number
    top_sources?: Array<{ source: string; count: number }>
  }
  insights: GlobalInsights | null
}> {
  const updatesPath = path.join(process.cwd(), 'public', 'data', 'updates.json')
  const metricsPath = path.join(process.cwd(), 'public', 'data', 'metrics.json')
  const insightsPath = path.join(process.cwd(), 'public', 'data', 'global_insights.json')
  const [updatesRaw, metricsRaw, insightsRaw] = await Promise.all([
    readFile(updatesPath, 'utf-8').catch(() => '[]'),
    readFile(metricsPath, 'utf-8').catch(() => '{}'),
    readFile(insightsPath, 'utf-8').catch(() => 'null'),
  ])
  const rows = JSON.parse(updatesRaw) as Row[]
  const metrics = JSON.parse(metricsRaw) as {
    generated_at?: string
    updates_total?: number
    pushed_total?: number
    dropped_total?: number
    sources_total?: number
    top_sources?: Array<{ source: string; count: number }>
  }
  const rawInsights = JSON.parse(insightsRaw) as GlobalInsights | null
  const insights = rawInsights
    ? {
        generated_at: rawInsights.generated_at,
        source_count: rawInsights.source_count,
        trends: asStringArray((rawInsights as Record<string, unknown>).trends),
        weak_signals: asStringArray((rawInsights as Record<string, unknown>).weak_signals),
        daily_advices: asStringArray((rawInsights as Record<string, unknown>).daily_advices),
      }
    : null
  return { rows: dedupeRows(rows).filter((r) => (r.score ?? 0) >= 0.6 || r.pushed), metrics, insights }
}

export default async function Page() {
  const useDb = Boolean(process.env.NEON_DATABASE_URL)
  const { rows, metrics: data, insights } = useDb ? await loadFromDb() : await loadFromFiles()

  return (
    <main className="main">
      <DashboardClient rows={rows} metrics={data} insights={insights} />
    </main>
  )
}

