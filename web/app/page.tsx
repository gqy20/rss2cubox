import { readFile } from 'node:fs/promises'
import path from 'node:path'
import DashboardClient from './DashboardClient'

async function loadData(): Promise<{
  rows: Array<{ id: string; title: string; url: string; source: string; time: string; score?: number }>
  metrics: {
    generated_at?: string
    updates_total?: number
    sources_total?: number
    top_sources?: Array<{ source: string; count: number }>
  }
}> {
  const updatesPath = path.join(process.cwd(), 'public', 'data', 'updates.json')
  const metricsPath = path.join(process.cwd(), 'public', 'data', 'metrics.json')
  const [updatesRaw, metricsRaw] = await Promise.all([
    readFile(updatesPath, 'utf-8').catch(() => '[]'),
    readFile(metricsPath, 'utf-8').catch(() => '{}'),
  ])
  const rows = JSON.parse(updatesRaw) as Array<{ id: string; title: string; url: string; source: string; time: string; score?: number }>
  const metrics = JSON.parse(metricsRaw) as {
    generated_at?: string
    updates_total?: number
    sources_total?: number
    top_sources?: Array<{ source: string; count: number }>
  }
  return { rows: rows.slice(0, 60), metrics }
}

export default async function Page() {
  const { rows, metrics: data } = await loadData()

  return (
    <main className="main">
      <DashboardClient rows={rows} metrics={data} />
    </main>
  )
}

