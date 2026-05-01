import DashboardClient from './DashboardClient'
import { headers } from 'next/headers'

import { loadGlobalInsights, loadArticles, loadLocalStats, type LocalStats } from '../lib/signalStore'
import { getBusinessDayKey } from '../lib/time'
import type { GlobalInsights, Row } from './types'

export const dynamic = 'force-dynamic'

function getRequestBaseUrl(requestHeaders: Headers): string {
  const host = requestHeaders.get('x-forwarded-host') || requestHeaders.get('host')
  if (!host) return process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:3424'

  const forwardedProto = requestHeaders.get('x-forwarded-proto')
  const protocol = forwardedProto || (/^(localhost|127\.0\.0\.1)(:\d+)?$/.test(host) ? 'http' : 'https')
  return `${protocol}://${host}`
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((v) => String(v)).filter((v) => v.trim().length > 0)
}

/**
 * 归一化后端 insight 字段，兼容新旧格式：
 *   新格式: { text, source_urls?, source_titles? }[]
 *   旧格式: string[]
 * 返回统一的前端展示格式 SignalItem[]
 */
function normalizeInsightField(raw: unknown): Array<{ text: string; source_urls?: string[]; source_titles?: string[] }> {
  if (!Array.isArray(raw)) return []
  return raw
    .map((item) => {
      if (typeof item === 'string') {
        const t = item.trim()
        return t.length > 0 ? { text: t } : null
      }
      if (item && typeof item === 'object' && !Array.isArray(item)) {
        const obj = item as Record<string, unknown>
        // 新格式
        if ('text' in obj && typeof obj.text === 'string') {
          const text = obj.text.trim()
          if (!text) return null
          const urls = Array.isArray(obj.source_urls)
            ? obj.source_urls.filter((u): u is string => typeof u === 'string' && Boolean(u.trim()))
            : []
          const titles = Array.isArray(obj.source_titles)
            ? obj.source_titles.filter((t): t is string => typeof t === 'string' && Boolean(t.trim()))
            : []
          return { text, source_urls: urls, source_titles: titles }
        }
        // 旧对象格式 { title, content } — 降级
        const title = String(obj.title ?? '').trim()
        if (title) return { text: title }
      }
      return null
    })
    .filter((item): item is NonNullable<typeof item> => item !== null)
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

  const topSources = localStats?.topSourceCounts
    ?? Object.entries(sourceCount)
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
    total_yesterday: localStats?.yesterday ?? totalYesterday,
    analyzed_today: localStats?.analyzedToday ?? analyzedToday,
    analyzed_yesterday: localStats?.analyzedYesterday ?? analyzedYesterday,
    sources_today: localStats?.sourcesToday ?? sourceToday.size,
    sources_yesterday: localStats?.sourcesYesterday ?? sourceYesterday.size,
    // 趋势数据
    timeline_points: trendData,
    // 每日数据量
    daily_totals: localStats?.dailyTotals ?? dailyCounts,
  }
}

async function loadDashboardData(apiBaseUrl?: string): Promise<{
  rows: Row[]
  metrics: ReturnType<typeof buildMetrics>
  insights: GlobalInsights | null
}> {
  // 获取今天的日期字符串（Asia/Shanghai 时区）
  const today = getDayKey(new Date())

  let events: ReturnType<typeof loadArticles> extends Promise<infer T> ? T : never = []
  let rawInsights: GlobalInsights | null = null
  let localStats: LocalStats | null = null
  try {
    // 并行加载：文章列表（只加载今天的数据用于初始展示）、统计数据（用于准确计数）、全局洞察
    const results = await Promise.allSettled([
      loadArticles(apiBaseUrl, today),
      loadLocalStats(apiBaseUrl),
      loadGlobalInsights(apiBaseUrl)
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
      content_source: e.content_source,
      signal_type: e.signal_type,
      evidence_strength: e.evidence_strength,
      novelty_score: e.novelty_score,
      impact_horizon: e.impact_horizon,
      confidence: e.confidence,
      entities: e.entities,
      watch_keywords: e.watch_keywords,
      prediction: e.prediction,
    })),
  )
  const insights = rawInsights
    ? {
        generated_at: rawInsights.generated_at,
        source_count: rawInsights.source_count,
        trends: normalizeInsightField(rawInsights.trends),
        weak_signals: normalizeInsightField(rawInsights.weak_signals),
        daily_advices: normalizeInsightField(rawInsights.daily_advices),
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
        metrics={data}
        insights={insights}
        serverTime={serverTime}
      />
    </main>
  )
}
