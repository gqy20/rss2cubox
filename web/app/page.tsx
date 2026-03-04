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

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((v) => String(v)).filter((v) => v.trim().length > 0)
}

async function loadData(): Promise<{
  rows: Array<{ id: string; title: string; url: string; source: string; time: string; score?: number }>
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
  const rows = JSON.parse(updatesRaw) as Array<{ id: string; title: string; url: string; source: string; time: string; score?: number }>
  const metrics = JSON.parse(metricsRaw) as {
    generated_at?: string
    updates_total?: number
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
  return { rows: rows.slice(0, 60), metrics, insights }
}

export default async function Page() {
  const { rows, metrics: data, insights } = await loadData()

  return (
    <main className="main">
      <DashboardClient rows={rows} metrics={data} insights={insights} />
    </main>
  )
}
