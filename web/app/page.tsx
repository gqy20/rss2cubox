import { readFile } from 'node:fs/promises'
import path from 'node:path'
import DashboardClient from './DashboardClient'

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

async function loadData(): Promise<{
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
  return { rows: dedupeRows(rows).filter(r => (r.score ?? 0) >= 0.6 || r.pushed), metrics, insights }
}

export default async function Page() {
  const { rows, metrics: data, insights } = await loadData()

  return (
    <main className="main">
      <DashboardClient rows={rows} metrics={data} insights={insights} />
    </main>
  )
}
