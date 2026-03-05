import DashboardClient from './DashboardClient'

import { loadGlobalInsights, loadRunEvents } from '../lib/neonDb'

export const revalidate = 1800 // 30 minutes; GitHub Actions triggers on-demand revalidation after each sync

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

function getDayKey(date: Date | string): string {
  const d = typeof date === 'string' ? new Date(date) : date
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function formatAxisDay(value: Date): string {
  const m = value.getMonth() + 1
  const d = value.getDate()
  return `${m}月${d}日`
}

function buildMetrics(rows: Row[]) {
  const now = new Date()
  const today = getDayKey(now)
  const yesterday = getDayKey(new Date(now.getTime() - 86400000))
  
  const sourceCount: Record<string, number> = {}
  let totalToday = 0, totalYesterday = 0
  let highToday = 0, highYesterday = 0
  const sourceToday = new Set<string>()
  const sourceYesterday = new Set<string>()
  
  for (const r of rows) {
    const source = r.source || 'unknown'
    sourceCount[source] = (sourceCount[source] ?? 0) + 1
    
    const dayKey = getDayKey(r.time)
    if (dayKey === today) {
      totalToday++
      if ((r.score ?? 0) >= 0.85) highToday++
      sourceToday.add(source)
    } else if (dayKey === yesterday) {
      totalYesterday++
      if ((r.score ?? 0) >= 0.85) highYesterday++
      sourceYesterday.add(source)
    }
  }
  
  const topSources = Object.entries(sourceCount)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([source, count]) => ({ source, count }))
    
  // 计算最近7天的趋势数据
  const dayMap = new Map<string, { name: string; total: number; high: number }>()
  const base = new Date()
  base.setHours(0, 0, 0, 0)
  for (let i = 6; i >= 0; i--) {
    const d = new Date(base)
    d.setDate(base.getDate() - i)
    const dayKey = getDayKey(d)
    dayMap.set(dayKey, { name: formatAxisDay(d), total: 0, high: 0 })
  }
  
  for (const r of rows) {
    const dayKey = getDayKey(r.time)
    const slot = dayMap.get(dayKey)
    if (slot) {
      slot.total++
      if ((r.score ?? 0) >= 0.85) slot.high++
    }
  }
  
  const trendData = Array.from(dayMap.values())

  // 计算每日数据量（用于右侧分组显示）
  const dailyCounts: Record<string, number> = {}
  for (const r of rows) {
    const dayKey = getDayKey(r.time)
    dailyCounts[dayKey] = (dailyCounts[dayKey] || 0) + 1
  }

  return {
    generated_at: new Date().toISOString(),
    updates_total: rows.length,
    pushed_total: rows.filter((r) => r.pushed).length,
    sources_total: Object.keys(sourceCount).length,
    top_sources: topSources,
    // KPI 数据
    total_all: rows.length,
    high_all: rows.filter((r) => (r.score ?? 0) >= 0.85).length,
    total_today: totalToday,
    total_yesterday: totalYesterday,
    high_today: highToday,
    high_yesterday: highYesterday,
    sources_today: sourceToday.size,
    sources_yesterday: sourceYesterday.size,
    // 趋势数据
    trend_data: trendData,
    // 每日数据量
    daily_counts: dailyCounts,
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

export const PAGE_SIZE = 50

export default async function Page() {
  const { rows, metrics: data, insights } = await loadFromDb()

    const paginatedRows = rows.slice(0, PAGE_SIZE)

  // 服务端时间，用于避免 hydration mismatch
  const serverTime = new Date().toISOString()

  return (
    <main className="main">
      <DashboardClient
        initialRows={paginatedRows}
        totalCount={rows.length}
        metrics={data}
        insights={insights}
        serverTime={serverTime}
      />
    </main>
  )
}

