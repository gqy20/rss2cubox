import DashboardClient from './DashboardClient'

import { loadGlobalInsights, loadIcArticles } from '../lib/signalStore'
import { getBusinessDayKey } from '../lib/time'
import type { GlobalInsights, Row } from './types'

export const revalidate = 1800 // 30 minutes; GitHub Actions triggers on-demand revalidation after each sync

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((v) => String(v)).filter((v) => v.trim().length > 0)
}

function getDayKey(value: Date | string): string {
  return getBusinessDayKey(value)
}

function hasAiSummary(row: Pick<Row, 'core_event' | 'hidden_signal' | 'actionable' | 'reason'>): boolean {
  return Boolean(row.core_event || row.hidden_signal || row.actionable || row.reason)
}

function formatAxisDay(value: Date): string {
  return value.toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric' })
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

function buildMetrics(rows: Row[]) {
  const now = new Date()
  const today = getDayKey(now)
  const yesterday = getDayKey(new Date(now.getTime() - 86400000))

  const sourceCount: Record<string, number> = {}
  let totalToday = 0, totalYesterday = 0
  let analyzedToday = 0, analyzedYesterday = 0
  const sourceToday = new Set<string>()
  const sourceYesterday = new Set<string>()

  for (const r of rows) {
    const source = r.source || 'unknown'
    sourceCount[source] = (sourceCount[source] ?? 0) + 1

    const dayKey = getDayKey(r.time)
    if (!dayKey) continue
    const analyzed = hasAiSummary(r)
    if (dayKey === today) {
      totalToday++
      if (analyzed) analyzedToday++
      sourceToday.add(source)
    } else if (dayKey === yesterday) {
      totalYesterday++
      if (analyzed) analyzedYesterday++
      sourceYesterday.add(source)
    }
  }

  const topSources = Object.entries(sourceCount)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([source, count]) => ({ source, count }))

  // 计算最近7天的趋势数据
  const dayMap = new Map<string, { name: string; total: number; analyzed: number }>()
  const base = new Date()
  base.setHours(0, 0, 0, 0)
  for (let i = 6; i >= 0; i--) {
    const d = new Date(base)
    d.setDate(base.getDate() - i)
    const dayKey = getDayKey(d)
    dayMap.set(dayKey, { name: formatAxisDay(d), total: 0, analyzed: 0 })
  }

  for (const r of rows) {
    const dayKey = getDayKey(r.time)
    if (!dayKey) continue
    const slot = dayMap.get(dayKey)
    if (slot) {
      slot.total++
      if (hasAiSummary(r)) slot.analyzed++
    }
  }

  const trendData = Array.from(dayMap.values())

  // 计算每日数据量（用于右侧分组显示）
  const dailyCounts: Record<string, number> = {}
  for (const r of rows) {
    const dayKey = getDayKey(r.time)
    if (!dayKey) continue
    dailyCounts[dayKey] = (dailyCounts[dayKey] || 0) + 1
  }

  return {
    generated_at: new Date().toISOString(),
    signals_total: rows.length,
    exported_total: rows.filter((r) => r.exported).length,
    active_sources_total: Object.keys(sourceCount).length,
    top_source_counts: topSources,
    // KPI 数据
    total_all: rows.length,
    analyzed_total: rows.filter((r) => hasAiSummary(r)).length,
    total_today: totalToday,
    total_yesterday: totalYesterday,
    analyzed_today: analyzedToday,
    analyzed_yesterday: analyzedYesterday,
    sources_today: sourceToday.size,
    sources_yesterday: sourceYesterday.size,
    // 趋势数据
    timeline_points: trendData,
    // 每日数据量
    daily_totals: dailyCounts,
  }
}

async function loadDashboardData(): Promise<{
  rows: Row[]
  metrics: ReturnType<typeof buildMetrics>
  insights: GlobalInsights | null
}> {
  const [events, rawInsights] = await Promise.all([loadIcArticles(), loadGlobalInsights()])
  const rows: Row[] = dedupeRows(
    events.map((e) => ({
      id: e.id,
      title: e.title,
      url: e.url,
      source: e.source,
      time: e.time,
      exported: e.exported,
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
  const { rows, metrics: data, insights } = await loadDashboardData()

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
