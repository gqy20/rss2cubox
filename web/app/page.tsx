import DashboardClient from './DashboardClient'
import { headers } from 'next/headers'

import { loadGlobalInsights, loadArticles, loadLocalStats, type LocalStats } from '../lib/signalStore'
import { getBusinessDayKey } from '../lib/time'
import type { GlobalInsights, Row } from './types'

export const dynamic = 'force-dynamic'

function getRequestBaseUrl(requestHeaders: Headers): string {
  const host = requestHeaders.get('x-forwarded-host') || requestHeaders.get('host')
  if (!host) return process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:3000'

  const forwardedProto = requestHeaders.get('x-forwarded-proto')
  const protocol = forwardedProto || (/^(localhost|127\.0\.0\.1)(:\d+)?$/.test(host) ? 'http' : 'https')
  return `${protocol}://${host}`
}

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

function buildMetrics(rows: Row[], localStats?: LocalStats | null) {
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

  // 计算最近30天的趋势数据，客户端再切换展示 7/30 天
  const dayMap = new Map<string, { name: string; total: number; analyzed: number }>()
  const base = new Date()
  base.setHours(0, 0, 0, 0)
  for (let i = 29; i >= 0; i--) {
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

  // 优先使用本地数据库的 trendData（准确），否则从 rows 计算
  const trendData = localStats?.trendData ?? Array.from(dayMap.values())

  // 计算每日数据量（用于右侧分组显示）
  const dailyCounts: Record<string, number> = {}
  for (const r of rows) {
    const dayKey = getDayKey(r.time)
    if (!dayKey) continue
    dailyCounts[dayKey] = (dailyCounts[dayKey] || 0) + 1
  }

  // 使用本地数据库统计的准确数据（如果可用）
  const signalsTotal = localStats?.total ?? rows.length
  const analyzedTotal = localStats?.analyzed ?? rows.filter((r) => hasAiSummary(r)).length
  const sourcesTotal = localStats?.sources ?? Object.keys(sourceCount).length

  return {
    generated_at: new Date().toISOString(),
    signals_total: signalsTotal,
    exported_total: signalsTotal,
    active_sources_total: sourcesTotal,
    top_source_counts: topSources,
    // KPI 数据
    total_all: signalsTotal,
    analyzed_total: analyzedTotal,
    total_today: localStats?.today ?? totalToday,
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

async function loadDashboardData(apiBaseUrl?: string): Promise<{
  rows: Row[]
  metrics: ReturnType<typeof buildMetrics>
  insights: GlobalInsights | null
}> {
  let events: ReturnType<typeof loadArticles> extends Promise<infer T> ? T : never = []
  let rawInsights: GlobalInsights | null = null
  let localStats: LocalStats | null = null
  try {
    // 并行加载：文章列表（只用于展示）、统计数据（用于准确计数）、全局洞察
    const results = await Promise.allSettled([
      loadArticles(apiBaseUrl),
      loadLocalStats(apiBaseUrl),
      loadGlobalInsights()
    ])
    events = results[0].status === 'fulfilled' ? results[0].value : []
    localStats = results[1].status === 'fulfilled' ? results[1].value : null
    rawInsights = results[2].status === 'fulfilled' ? results[2].value : null
  } catch {
    // Build env may not reach IC API / DB — client will fetch via API route
  }
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
      importance_score: e.importance_score,
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
  return { rows, metrics: buildMetrics(rows, localStats), insights }
}

export const PAGE_SIZE = 50

export default async function Page() {
  const requestHeaders = await headers()
  const { rows, metrics: data, insights } = await loadDashboardData(getRequestBaseUrl(requestHeaders))

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
