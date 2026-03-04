import { readFile } from 'node:fs/promises'
import path from 'node:path'

function formatTime(value: string): string {
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString()
}

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
      <h1 className="h1">RSS Signal Wall</h1>
      <div className="muted">Auto-updated by GitHub Actions commit. Vercel redeploys on every new commit.</div>

      <section className="kpi">
        <article className="card">
          <div className="small">Updates</div>
          <div className="value">{data.updates_total ?? 0}</div>
        </article>
        <article className="card">
          <div className="small">Sources</div>
          <div className="value">{data.sources_total ?? 0}</div>
        </article>
        <article className="card">
          <div className="small">Generated</div>
          <div className="value" style={{ fontSize: 14 }}>{formatTime(data.generated_at ?? '')}</div>
        </article>
      </section>

      <h2 style={{ marginTop: 24 }}>Latest Updates</h2>
      <section className="grid">
        {rows.map((row) => (
          <article key={row.id} className="card">
            <div className="small">{row.source}</div>
            <h3 className="title">{row.title}</h3>
            <div className="small">score: {typeof row.score === 'number' ? row.score.toFixed(2) : '0.00'}</div>
            <div className="small">{formatTime(row.time)}</div>
            <a className="link" href={row.url} target="_blank" rel="noreferrer">Open</a>
          </article>
        ))}
      </section>
    </main>
  )
}
