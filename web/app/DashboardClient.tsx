'use client'

import { useState, useMemo, useEffect, useRef, useCallback } from 'react'
import { useSearch } from '../hooks/useSearch'
import { useGroupData } from '../hooks/useGroupData'
import { useInfiniteScroll } from '../hooks/useInfiniteScroll'
import dynamic from 'next/dynamic'
import {
  TrendingUp,
  Radio,
  Lightbulb,
} from 'lucide-react'
import {
  getDayKey,
  formatGroupTitle,
  formatKpiDelta,
  hasAiSummary,
} from './utils'
import type { Row, Metrics, GlobalInsights, InsightKey } from './types'
import { loadAllGlobalInsights, type InsightHistoryItem, type LocalStats } from '../lib/signalStore'
import { DashboardLeft, DashboardRight, type KpiItem, type ParsedInsightItem } from './DashboardSections'

const LIVE_REFRESH_INTERVAL_MS = 60_000

type ChartsSectionProps = {
  trendData: Array<{ name: string; total: number; analyzed: number }>
  sourceData: Array<{ name: string; value: number }>
  selectedSource: string | null
  onSelectSource: (source: string | null | ((prev: string | null) => string | null)) => void
  onDateClick?: (dayKey: string) => void
  timeRange: '7d' | '30d'
  onTimeRangeChange: (range: '7d' | '30d') => void
  insightHistory?: InsightHistoryItem[]
  selectedInsightIdx: number
  onSelectInsight: (idx: number) => void
}

const ChartsSection = dynamic<ChartsSectionProps>(() => import('./charts-section').then((m) => m.default), {
  ssr: false,
  loading: () => (
    <section className="charts-grid charts-section-spaced">
      <div className="glass chart-card chart-loading-card">
        图表加载中...
      </div>
      <div className="glass chart-card chart-loading-card">
        图表加载中...
      </div>
    </section>
  ),
})

type Props = {
  serverTime?: string
  initialRows: Row[]
  metrics: Metrics
  insights?: GlobalInsights | null
}

function parseInsightString(raw: string): ParsedInsightItem {
  const text = raw.trim()
  if (!text) return { title: '' }

  const titleMatch = text.match(/["']title["']\s*:\s*["']([\s\S]*?)["']\s*(,|})/)
  const contentMatch = text.match(/["']content["']\s*:\s*["']([\s\S]*?)["']\s*(,|})/)

  if (titleMatch?.[1]) {
    const title = titleMatch[1].trim()
    const content = contentMatch?.[1]?.trim()
    return { title, content }
  }

  // Compatible with Python-like payload strings: {'id': 1, 'content': '...'}
  const pyContentMatch = text.match(/['"]content['"]\s*:\s*['"]([\s\S]*?)['"]\s*(,|})/)
  if (pyContentMatch?.[1]) {
    return { title: pyContentMatch[1].trim() }
  }

  return { title: text }
}

function normalizeInsightItems(items: unknown[]): ParsedInsightItem[] {
  if (!Array.isArray(items)) return []
  return items
    .map((item): ParsedInsightItem | null => {
      // 新格式: { text, source_urls?, source_titles? }
      if (item && typeof item === 'object' && !Array.isArray(item)) {
        const obj = item as Record<string, unknown>
        if ('text' in obj && typeof obj.text === 'string') {
          const text = obj.text.trim()
          if (!text) return null
          const urls = Array.isArray(obj.source_urls)
            ? obj.source_urls.filter((u): u is string => typeof u === 'string' && Boolean(u.trim()))
            : []
          const titles = Array.isArray(obj.source_titles)
            ? obj.source_titles.filter((t): t is string => typeof t === 'string' && Boolean(t.trim()))
            : []
          return { title: text, content: undefined, sourceUrls: urls, sourceTitles: titles }
        }
        // 旧对象格式: { title, content? }
        const title = String(obj.title ?? '').trim()
        const content = String(obj.content ?? '').trim()
        if (title) return { title, content: content || undefined }
        if (content) return { title: content }
        return null
      }
      // 旧格式: 纯字符串
      if (typeof item === 'string') return parseInsightString(item)
      return { title: String(item ?? '').trim() }
    })
    .filter((item): item is ParsedInsightItem => item !== null && item.title.length > 0)
}

function statsToMetrics(stats: LocalStats, previous: Metrics): Metrics {
  return {
    ...previous,
    generated_at: new Date().toISOString(),
    signals_total: stats.total,
    exported_total: stats.total,
    active_sources_total: stats.sources,
    top_source_counts: stats.topSourceCounts ?? previous.top_source_counts,
    total_all: stats.total,
    analyzed_total: stats.analyzed,
    total_today: stats.today,
    total_yesterday: stats.yesterday,
    analyzed_today: stats.analyzedToday,
    analyzed_yesterday: stats.analyzedYesterday,
    sources_today: stats.sourcesToday,
    sources_yesterday: stats.sourcesYesterday,
    timeline_points: stats.trendData ?? previous.timeline_points,
    daily_totals: stats.dailyTotals ?? previous.daily_totals,
  }
}

export default function DashboardClient({ initialRows, metrics: initialMetrics, insights, serverTime }: Props) {
  const [metrics, setMetrics] = useState<Metrics>(initialMetrics)
  const formatGeneratedAt = (value?: string) => {
    if (!value) return '未知'
    const dt = new Date(value)
    if (Number.isNaN(dt.getTime())) return '未知'
    return dt.toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  }

  // Hook: 搜索状态管理（替换 7 个独立 state + debounce + abort + auto-fetch）
  const { search, searchRows, searchPage, searchTotal, searchHasMore, searchLoading, isSearchMode, setSearch, fetchSearchPage } = useSearch()

  // 分组数据状态（组件拥有，支持 SSR props 初始化）
  const [groupData, setGroupData] = useState<Record<string, { loading: boolean; loaded: boolean; items: Row[]; hasMore: boolean }>>({})
  const [groupPaging, setGroupPaging] = useState<Record<string, { page: number }>>({})
  const allDates = useMemo(() => Object.keys(metrics.daily_totals || {}).sort((a, b) => b.localeCompare(a)), [metrics.daily_totals])

  // Hook: 分组数据操作（外部状态注入模式，回调操作组件的 state）
  const { loadGroupData, loadMoreForGroup, nextUnloadedDate } = useGroupData({ groupData, setGroupData, groupPaging, setGroupPaging, allDates })

  const [loadingMore, setLoadingMore] = useState(false)
  const [filter, setFilter] = useState<'all' | 'analyzed' | 'high_value'>('all')
  const [selectedSource, setSelectedSource] = useState<string | null>(null)
  const [selectedTag, setSelectedTag] = useState<string | null>(null)
  const [hoveredRowKey, setHoveredRowKey] = useState<string | null>(null)
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({})
  const [dateMenuOpen, setDateMenuOpen] = useState(false)
  const [dateQuery, setDateQuery] = useState('')
  const [selectedDateKey, setSelectedDateKey] = useState<string | null>(() => getDayKey(new Date()))

  const [actionMessage, setActionMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [shouldLoadCharts, setShouldLoadCharts] = useState(false)

  const [now, setNow] = useState<Date | null>(serverTime ? new Date(serverTime) : null)

  // Insights 历史记录状态
  const [insightsHistory, setInsightsHistory] = useState<InsightHistoryItem[]>([])
  const [selectedInsightIdx, setSelectedInsightIdx] = useState<number>(0)
  const [selectedInsightKey, setSelectedInsightKey] = useState<InsightKey>('daily_advices')

  // 趋势图表时间范围状态
  const [timeRange, setTimeRange] = useState<'7d' | '30d'>('7d')

  // 加载 Insights 历史记录
  useEffect(() => {
    loadAllGlobalInsights(30)
      .then((history) => {
        setInsightsHistory(history)
        if (history.length > 0) {
          setSelectedInsightIdx(0)
        }
      })
      .catch(() => console.error('Failed to load insights history'))
  }, [])

  // 当前选中的 insights
  const currentInsights = insightsHistory[selectedInsightIdx]?.data ?? insights ?? null

  // 初始化：只加载今天的数据
  useEffect(() => {
    const today = getDayKey(new Date())
    const todayItems = initialRows.filter((r) => getDayKey(r.time) === today)
    const todayCount = initialMetrics.daily_totals?.[today] || 0
    setGroupData({
      [today]: {
        loading: false,
        loaded: todayItems.length > 0,
        items: todayItems,
        hasMore: todayCount > todayItems.length,
      }
    })
    setGroupPaging({
      [today]: { page: 1 },
    })
  }, [initialRows, initialMetrics.daily_totals])
  
  const searchRef = useRef<HTMLInputElement>(null)
  const chartsTriggerRef = useRef<HTMLDivElement>(null)
  const timelineRef = useRef<HTMLDivElement>(null)
  const loadMoreRef = useRef<HTMLDivElement>(null)
  const groupRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const hoverCloseTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})

  // Side Effects

  useEffect(() => {
    setNow(new Date())
    const timer = setInterval(() => setNow(new Date()), 60000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    timelineRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
  }, [filter, selectedSource, selectedTag, search])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === '/' && document.activeElement?.tagName !== 'INPUT') {
        e.preventDefault()
        searchRef.current?.focus()
      }
      if (e.key.toLowerCase() === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        searchRef.current?.focus()
      }
      if (e.key === 'Escape') {
        setSearch('')
        setSelectedSource(null)
        setSelectedTag(null)
        searchRef.current?.blur()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  useEffect(() => {
    return () => {
      Object.values(hoverCloseTimers.current).forEach((timer) => clearTimeout(timer))
    }
  }, [])

  useEffect(() => {
    const target = chartsTriggerRef.current
    if (!target || shouldLoadCharts) return

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setShouldLoadCharts(true)
          observer.disconnect()
        }
      },
      { rootMargin: '200px 0px' },
    )

    observer.observe(target)
    return () => observer.disconnect()
  }, [shouldLoadCharts])

  // Derived State

  const todayKey = useMemo(() => getDayKey(now ?? new Date()), [now])
  const yesterdayKey = useMemo(() => {
    const d = new Date(now ?? new Date())
    d.setDate(d.getDate() - 1)
    return getDayKey(d)
  }, [now])

  const refreshDashboardData = useCallback(async () => {
    try {
      const [statsRes, todayRowsRes] = await Promise.all([
        fetch('/api/signals/local/stats', { cache: 'no-store' }),
        fetch(`/api/signals?page=1&limit=50&date=${todayKey}`, { cache: 'no-store' }),
      ])

      if (statsRes.ok) {
        const stats = await statsRes.json() as LocalStats
        setMetrics((prev) => statsToMetrics(stats, prev))
      }

      if (todayRowsRes.ok) {
        const todayPayload = await todayRowsRes.json() as { data?: Row[]; hasMore?: boolean }
        if (Array.isArray(todayPayload.data)) {
          setGroupData((prev) => ({
            ...prev,
            [todayKey]: {
              loading: false,
              loaded: true,
              items: todayPayload.data ?? [],
              hasMore: Boolean(todayPayload.hasMore),
            },
          }))
          setGroupPaging((prev) => ({ ...prev, [todayKey]: { page: 1 } }))
        }
      }
    } catch (error) {
      console.error('Failed to refresh dashboard data:', error)
    }
  }, [todayKey])

  useEffect(() => {
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') void refreshDashboardData()
    }, LIVE_REFRESH_INTERVAL_MS)

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') void refreshDashboardData()
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [refreshDashboardData])

  // 情报源列表（用于筛选）
  const topSourceNames = useMemo(() => {
    const sources = metrics.top_source_counts || []
    return sources.slice(0, 5).map((s: { source: string }) => s.source)
  }, [metrics.top_source_counts])

  const loadedRows = useMemo(() => {
    const allItems: Row[] = []
    Object.values(groupData).forEach((group) => {
      if (group.loaded) allItems.push(...group.items)
    })
    return allItems
  }, [groupData])

  // 展示数据：搜索模式使用后端检索结果，非搜索模式使用已加载分组
  const displayedRows = useMemo(() => {
    const baseRows = isSearchMode ? searchRows : loadedRows
    let result = [...baseRows]
    if (filter === 'analyzed') result = result.filter((r) => hasAiSummary(r))
    if (filter === 'high_value') result = result.filter((r) => (r.importance_score ?? 0) >= 4)
    if (!isSearchMode && selectedDateKey) result = result.filter((r) => getDayKey(r.time) === selectedDateKey)
    if (selectedSource) {
      if (selectedSource === '__others__') {
        const topSet = new Set(topSourceNames)
        result = result.filter((r) => !topSet.has(r.source || 'unknown'))
      } else {
        result = result.filter((r) => r.source === selectedSource)
      }
    }
    if (selectedTag) result = result.filter((r) => (r.tags || []).includes(selectedTag))
    return result.sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime())
  }, [isSearchMode, searchRows, loadedRows, filter, selectedDateKey, selectedSource, selectedTag, topSourceNames])

  // 趋势数据来自服务端（基于全部数据），图表按当前范围展示最近 7/30 天
  const trendData = useMemo(() => {
    const points = metrics.timeline_points || []
    const sliced = points.slice(timeRange === '7d' ? -7 : -30)
    // 为缺少 dayKey 的数据点补上 dayKey（从 name "MM/DD" 反推）
    const baseDate = new Date()
    baseDate.setHours(0, 0, 0, 0)
    return sliced.map((pt, i) => {
      if (pt.dayKey) return pt
      const d = new Date(baseDate)
      d.setDate(baseDate.getDate() - (sliced.length - 1 - i))
      const dk = getDayKey(d)
      return { ...pt, dayKey: dk }
    })
  }, [metrics.timeline_points, timeRange])

  // 情报源分布来自服务端（基于全部数据）
  const sourceData = useMemo(() => {
    const topSources = metrics.top_source_counts || []
    const rawData = topSources.map((s: { source: string; count: number }) => ({ name: s.source, value: s.count }))
    const top5 = rawData.slice(0, 5)
    const others = rawData.slice(5)
    if (others.length > 0) top5.push({ name: '其他', value: others.reduce((sum, item) => sum + item.value, 0) })
    return top5
  }, [metrics.top_source_counts])

  // 按日期分组：搜索模式仅显示命中日期，非搜索模式显示所有日期并懒加载
  const groupedRows = useMemo(() => {
    const dateMap = new Map<string, Row[]>()
    for (const row of displayedRows) {
      const key = getDayKey(row.time)
      if (!dateMap.has(key)) dateMap.set(key, [])
      dateMap.get(key)?.push(row)
    }

    if (isSearchMode) {
      return Array.from(dateMap.keys())
        .sort((a, b) => b.localeCompare(a))
        .map((dayKey) => ({
          id: dayKey,
          title: formatGroupTitle(dayKey, todayKey, yesterdayKey),
          items: dateMap.get(dayKey) || [],
          total: (dateMap.get(dayKey) || []).length,
          loaded: true,
        }))
    }

    const visibleDates = selectedDateKey ? [selectedDateKey] : allDates

    return visibleDates.map((dayKey) => ({
      id: dayKey,
      title: formatGroupTitle(dayKey, todayKey, yesterdayKey),
      items: dateMap.get(dayKey) || [],
      total: metrics.daily_totals?.[dayKey] || 0,
      loaded: !!dateMap.get(dayKey)?.length,
    }))
  }, [isSearchMode, allDates, selectedDateKey, displayedRows, todayKey, yesterdayKey, metrics.daily_totals])

  const filteredDateOptions = useMemo(() => {
    const query = dateQuery.trim().toLowerCase()
    if (!query) return allDates
    return allDates.filter((dayKey) => {
      const label = formatGroupTitle(dayKey, todayKey, yesterdayKey)
      return dayKey.includes(query) || label.toLowerCase().includes(query)
    })
  }, [allDates, dateQuery, todayKey, yesterdayKey])
  const hasLoadingGroup = useMemo(
    () => groupedRows.some((group) => groupData[group.id]?.loading),
    [groupedRows, groupData],
  )

  const insightPanels = useMemo(
    () => [
      { key: 'trends' as InsightKey, title: '宏观技术趋势', icon: <TrendingUp size={16} color="#2dd4bf" />, items: normalizeInsightItems(Array.isArray(currentInsights?.trends) ? currentInsights.trends : []) },
      { key: 'weak_signals' as InsightKey, title: '暗流弱信号', icon: <Radio size={16} color="#f59e0b" />, items: normalizeInsightItems(Array.isArray(currentInsights?.weak_signals) ? currentInsights.weak_signals : []) },
      { key: 'daily_advices' as InsightKey, title: '今日行动建议', icon: <Lightbulb size={16} color="#a78bfa" />, items: normalizeInsightItems(Array.isArray(currentInsights?.daily_advices) ? currentInsights.daily_advices : []) },
    ],
    [currentInsights]
  )
  const visibleInsightPanels = useMemo(() => insightPanels.filter((panel) => panel.items.length > 0), [insightPanels])
  const activeInsightPanel = useMemo(
    () => visibleInsightPanels.find((panel) => panel.key === selectedInsightKey) ?? visibleInsightPanels[0],
    [selectedInsightKey, visibleInsightPanels],
  )

  // KPI 使用服务端计算的完整数据
  const kpis: KpiItem[] = [
    { key: 'all', title: '有效信号', value: metrics.signals_total ?? 0, tone: 'var(--accent)', delta: null, onClick: () => { setFilter('all'); setSelectedDateKey(null) } },
    { key: 'analyzed', title: '已分析', value: metrics.analyzed_total ?? 0, tone: '#34d399', delta: null, onClick: () => { setFilter('analyzed'); setSelectedDateKey(null) } },
    { key: 'today', title: '今日新增', value: metrics.total_today ?? 0, tone: '#60a5fa', delta: formatKpiDelta(metrics.total_today ?? 0, metrics.total_yesterday ?? 0), onClick: () => { setFilter('all'); setSelectedDateKey(todayKey); setCollapsedGroups((prev) => ({ ...prev, [todayKey]: false })); void loadGroupData(todayKey); timelineRef.current?.scrollTo({ top: 0, behavior: 'smooth' }) } },
    { key: 'source', title: '活跃情报源', value: metrics.active_sources_total ?? 0, tone: '#a78bfa', delta: null, onClick: () => setSelectedSource(null) },
  ]

  // Handlers

  const getTailVisibleGroupId = useCallback((): string | null => {
    const root = timelineRef.current
    if (!root) return null

    const rootRect = root.getBoundingClientRect()
    let tailId: string | null = null
    let tailTop = -Infinity

    for (const group of groupedRows) {
      const el = groupRefs.current[group.id]
      if (!el) continue
      const rect = el.getBoundingClientRect()
      const inLowerViewport = rect.top <= rootRect.bottom - 24
      if (inLowerViewport && rect.top > tailTop) {
        tailTop = rect.top
        tailId = group.id
      }
    }

    return tailId
  }, [groupedRows])

  const maybeLoadMore = useCallback(() => {
    if (loadingMore) return

    if (isSearchMode) {
      if (!searchHasMore || searchLoading) return
      void fetchSearchPage(searchPage + 1, true)
      return
    }

    if (selectedDateKey) {
      const selectedGroup = groupData[selectedDateKey]
      if (!selectedGroup?.loaded && !selectedGroup?.loading) {
        setLoadingMore(true)
        void loadGroupData(selectedDateKey).finally(() => setLoadingMore(false))
        return
      }
      if (selectedGroup?.loaded && !selectedGroup.loading && selectedGroup.hasMore) {
        setLoadingMore(true)
        void loadMoreForGroup(selectedDateKey).finally(() => setLoadingMore(false))
      }
      return
    }

    const tailGroupId = getTailVisibleGroupId()
    if (tailGroupId) {
      const tailGroup = groupData[tailGroupId]
      if (tailGroup?.loaded && !tailGroup.loading && tailGroup.hasMore) {
        setLoadingMore(true)
        void loadMoreForGroup(tailGroupId).finally(() => setLoadingMore(false))
        return
      }
    }

    const todayGroup = groupData[todayKey]
    if (todayGroup?.loaded && !todayGroup.loading && todayGroup.hasMore && tailGroupId === todayKey) {
      setLoadingMore(true)
      void loadMoreForGroup(todayKey).finally(() => setLoadingMore(false))
      return
    }

    if (!nextUnloadedDate) return
    setLoadingMore(true)
    void loadGroupData(nextUnloadedDate).finally(() => setLoadingMore(false))
  }, [loadingMore, isSearchMode, searchHasMore, searchLoading, fetchSearchPage, searchPage, selectedDateKey, groupData, loadGroupData, loadMoreForGroup, getTailVisibleGroupId, todayKey, nextUnloadedDate])

  // Hook: 统一无限滚动（替换原来的 IO + scroll 双监听）
  useInfiniteScroll({
    rootRef: timelineRef,
    sentinelRef: loadMoreRef,
    onLoadMore: maybeLoadMore,
    loading: loadingMore,
    rootMargin: '0px 0px 240px 0px',
  })

  const clearAllFilters = () => {
    setSearch(''); setSelectedSource(null); setSelectedTag(null); setSelectedDateKey(null); setFilter('all')
  }

  const jumpToDateGroup = useCallback((dayKey: string) => {
    if (!dayKey) return
    if (isSearchMode) {
      setSearch('')
    }
    setSelectedDateKey(dayKey)

    const scrollToGroup = () => {
      setCollapsedGroups((prev) => ({ ...prev, [dayKey]: false }))
      requestAnimationFrame(() => {
        groupRefs.current[dayKey]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      })
    }

    const groupState = groupData[dayKey]
    if (!isSearchMode && !groupState?.loaded && !groupState?.loading) {
      void loadGroupData(dayKey).then(scrollToGroup)
      return
    }

    if (groupRefs.current[dayKey]) {
      scrollToGroup()
      return
    }

    timelineRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
  }, [isSearchMode, groupData, loadGroupData, setSearch])

  const openRowHover = (key: string) => {
    const timer = hoverCloseTimers.current[key]
    if (timer) { clearTimeout(timer); delete hoverCloseTimers.current[key] }
    setHoveredRowKey(key)
  }

  const closeRowHover = (key: string) => {
    hoverCloseTimers.current[key] = setTimeout(() => {
      setHoveredRowKey((prev) => (prev === key ? null : prev))
      delete hoverCloseTimers.current[key]
    }, 140)
  }

  const toggleRowOpen = (key: string) => {
    const timer = hoverCloseTimers.current[key]
    if (timer) { clearTimeout(timer); delete hoverCloseTimers.current[key] }
    setHoveredRowKey((prev) => (prev === key ? null : key))
  }

  const setMessage = (type: 'success' | 'error', text: string) => {
    setActionMessage({ type, text })
    setTimeout(() => setActionMessage(null), 3200)
  }

  const copyInsightText = async (title: string, items: ParsedInsightItem[]) => {
    const text = `${title}\n\n${items
      .map((item, i) => {
        let line = `${i + 1}. ${item.title}`
        if (item.content) line += `\n   ${item.content}`
        if (item.sourceUrls && item.sourceUrls.length > 0) {
          line += '\n   来源: ' + item.sourceUrls.map((url, j) => {
            const label = item.sourceTitles?.[j] || url
            return `${label} (${url})`
          }).join(' | ')
        }
        return line
      })
      .join('\n')}`

    const fallbackCopy = () => {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.setAttribute('readonly', 'true')
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      ta.style.pointerEvents = 'none'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      return ok
    }

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
      } else if (!fallbackCopy()) {
        throw new Error('copy_failed')
      }
      setMessage('success', `${title} 已复制`)
    } catch {
      if (fallbackCopy()) {
        setMessage('success', `${title} 已复制`)
      } else {
        setMessage('error', '复制失败')
      }
    }
  }

  const downloadRowsAsJson = (rowsToDownload: Row[], label: string) => {
    if (rowsToDownload.length === 0) { setMessage('error', `${label} 没有可导出的条目`); return }
    const payload = { generated_at: new Date().toISOString(), label, total: rowsToDownload.length, items: rowsToDownload }
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `rss-export-${label}-${new Date().toISOString().replace(/[:.]/g, '-')}.json`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    setMessage('success', `已下载 ${label} JSON（${rowsToDownload.length} 条）`)
  }

  return (
    <>
      <DashboardLeft
        generatedAt={formatGeneratedAt(metrics.generated_at)}
        kpis={kpis}
        activeInsightPanel={activeInsightPanel}
        visibleInsightPanels={visibleInsightPanels}
        onSelectInsightKey={setSelectedInsightKey}
        onCopyInsight={copyInsightText}
        onExport={() => downloadRowsAsJson(displayedRows.slice(0, 500), '当前筛选')}
        chartsTriggerRef={chartsTriggerRef}
        shouldLoadCharts={shouldLoadCharts}
        onLoadCharts={() => setShouldLoadCharts(true)}
        chartsNode={
            <ChartsSection
              trendData={trendData}
              sourceData={sourceData}
              selectedSource={selectedSource}
              onSelectSource={setSelectedSource}
              onDateClick={jumpToDateGroup}
              timeRange={timeRange}
              onTimeRangeChange={setTimeRange}
              insightHistory={insightsHistory}
              selectedInsightIdx={selectedInsightIdx}
              onSelectInsight={setSelectedInsightIdx}
            />
        }
        actionMessage={actionMessage}
      />

      <DashboardRight
        search={search}
        searchRef={searchRef}
        onSearchChange={setSearch}
        filter={filter}
        onFilterChange={setFilter}
        selectedDateKey={selectedDateKey}
        todayKey={todayKey}
        yesterdayKey={yesterdayKey}
        dateMenuOpen={dateMenuOpen}
        onDateMenuOpenChange={setDateMenuOpen}
        dateQuery={dateQuery}
        onDateQueryChange={setDateQuery}
        filteredDateOptions={filteredDateOptions}
        metrics={metrics}
        selectedSource={selectedSource}
        selectedTag={selectedTag}
        onClearSource={() => setSelectedSource(null)}
        onClearTag={() => setSelectedTag(null)}
        onClearAll={clearAllFilters}
        onToggleToday={() => {
          if (selectedDateKey === todayKey) {
            setSelectedDateKey(null)
          } else {
            setSelectedDateKey(todayKey)
            void loadGroupData(todayKey)
            timelineRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
          }
        }}
        onJumpToDate={jumpToDateGroup}
        onExport={() => downloadRowsAsJson(displayedRows.slice(0, 500), '当前筛选')}
        displayedRows={displayedRows}
        isSearchMode={isSearchMode}
        searchTotal={searchTotal}
        hasLoadingGroup={hasLoadingGroup}
        groupedRows={groupedRows}
        groupData={groupData}
        collapsedGroups={collapsedGroups}
        setCollapsedGroups={setCollapsedGroups}
        loadGroupData={loadGroupData}
        timelineRef={timelineRef}
        loadMoreRef={loadMoreRef}
        groupRefs={groupRefs}
        now={now}
        hoveredRowKey={hoveredRowKey}
        onHoverEnter={openRowHover}
        onHoverLeave={closeRowHover}
        onToggleOpen={toggleRowOpen}
        onTagClick={(tag) => setSelectedTag((prev) => (prev === tag ? null : tag))}
        searchLoading={searchLoading}
        loadingMore={loadingMore}
      />
    </>
  )
}
