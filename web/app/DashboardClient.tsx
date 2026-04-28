'use client'

import { useState, useMemo, useEffect, useRef, useCallback } from 'react'
import { useSearch } from '../hooks/useSearch'
import { useGroupData } from '../hooks/useGroupData'
import { useInfiniteScroll } from '../hooks/useInfiniteScroll'
import dynamic from 'next/dynamic'
import {
  Filter,
  TrendingUp,
  Radio,
  Lightbulb,
  Search,
  ArrowUpDown,
  Copy,
  ChevronDown,
  ChevronUp,
  Check,
  AlertCircle,
  Download,
} from 'lucide-react'
import {
  Logo,
  AnimatedNumber,
  getDayKey,
  formatGroupTitle,
  formatKpiDelta,
  hasAiSummary,
} from './utils'
import FeedCard from './FeedCard'
import type { Row, Metrics, GlobalInsights, InsightKey } from './types'
import { loadAllGlobalInsights, type InsightHistoryItem } from '../lib/signalStore'

type ChartsSectionProps = {
  trendData: Array<{ name: string; total: number; analyzed: number }>
  sourceData: Array<{ name: string; value: number }>
  selectedSource: string | null
  onSelectSource: (source: string | null | ((prev: string | null) => string | null)) => void
  timeRange: '7d' | '30d'
  onTimeRangeChange: (range: '7d' | '30d') => void
  insightHistory?: InsightHistoryItem[]
  selectedInsightIdx: number
  onSelectInsight: (idx: number) => void
}

const ChartsSection = dynamic<ChartsSectionProps>(() => import('./charts-section').then((m) => m.default), {
  ssr: false,
  loading: () => (
    <section className="charts-grid" style={{ marginBottom: 18 }}>
      <div className="glass chart-card" style={{ display: 'grid', placeItems: 'center', minHeight: 280, color: '#8aa3be' }}>
        图表加载中...
      </div>
      <div className="glass chart-card" style={{ display: 'grid', placeItems: 'center', minHeight: 280, color: '#8aa3be' }}>
        图表加载中...
      </div>
    </section>
  ),
})

type Props = {
  serverTime?: string
  initialRows: Row[]
  totalCount: number
  metrics: Metrics
  insights?: GlobalInsights | null
}

type ParsedInsightItem = {
  title: string
  content?: string
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
  return items
    .map((item) => {
      if (typeof item === 'string') return parseInsightString(item)
      if (item && typeof item === 'object') {
        const value = item as Record<string, unknown>
        const title = String(value.title || '').trim()
        const content = String(value.content || '').trim()
        if (title) return { title, content: content || undefined }
        if (content) return { title: content }
        return { title: JSON.stringify(item) }
      }
      return { title: String(item ?? '').trim() }
    })
    .filter((item) => item.title.length > 0)
}

export default function DashboardClient({ initialRows, totalCount, metrics, insights, serverTime }: Props) {
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
  const { search, debouncedSearch, searchRows, searchPage, searchTotal, searchHasMore, searchLoading, isSearchMode, setSearch, fetchSearchPage } = useSearch()

  // 分组数据状态（组件拥有，支持 SSR props 初始化）
  const [groupData, setGroupData] = useState<Record<string, { loading: boolean; loaded: boolean; items: Row[]; hasMore: boolean }>>({})
  const [groupPaging, setGroupPaging] = useState<Record<string, { page: number }>>({})
  const allDates = useMemo(() => Object.keys(metrics.daily_totals || {}).sort((a, b) => b.localeCompare(a)), [metrics.daily_totals])

  // Hook: 分组数据操作（外部状态注入模式，回调操作组件的 state）
  const { loadGroupData, loadMoreForGroup, nextUnloadedDate } = useGroupData({ groupData, setGroupData, groupPaging, setGroupPaging, allDates })

  const [loadingMore, setLoadingMore] = useState(false)
  const [filter, setFilter] = useState<'all' | 'analyzed'>('all')
  const [timeScope, setTimeScope] = useState<'all' | 'today'>('all')
  const [selectedSource, setSelectedSource] = useState<string | null>(null)
  const [selectedTag, setSelectedTag] = useState<string | null>(null)
  const [hoveredRowKey, setHoveredRowKey] = useState<string | null>(null)
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({})

  const [actionMessage, setActionMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [shouldLoadCharts, setShouldLoadCharts] = useState(false)

  const [now, setNow] = useState<Date | null>(serverTime ? new Date(serverTime) : null)

  // Insights 历史记录状态
  const [insightsHistory, setInsightsHistory] = useState<InsightHistoryItem[]>([])
  const [selectedInsightIdx, setSelectedInsightIdx] = useState<number>(0)
  const [insightsLoading, setInsightsLoading] = useState(false)

  // 趋势图表时间范围状态
  const [timeRange, setTimeRange] = useState<'7d' | '30d'>('7d')

  // 加载 Insights 历史记录
  useEffect(() => {
    setInsightsLoading(true)
    loadAllGlobalInsights(30)
      .then((history) => {
        setInsightsHistory(history)
        if (history.length > 0) {
          setSelectedInsightIdx(0)
        }
      })
      .catch(() => console.error('Failed to load insights history'))
      .finally(() => setInsightsLoading(false))
  }, [])

  // 当前选中的 insights
  const currentInsights = insightsHistory[selectedInsightIdx]?.data ?? insights ?? null

  // 初始化：只加载今天的 20 条数据
  useEffect(() => {
    const today = getDayKey(new Date())
    const todayItems = initialRows.filter((r) => getDayKey(r.time) === today)
    const todayCount = metrics.daily_totals?.[today] || 0
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
  }, [initialRows, metrics.daily_totals])
  
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
  }, [filter, timeScope, selectedSource, selectedTag, search])

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
    let result = filter === 'analyzed' ? baseRows.filter((r) => hasAiSummary(r)) : [...baseRows]
    if (timeScope === 'today') result = result.filter((r) => getDayKey(r.time) === todayKey)
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
  }, [isSearchMode, searchRows, loadedRows, filter, timeScope, selectedSource, selectedTag, todayKey, topSourceNames])

  // 趋势数据来自服务端（基于全部数据）
  const trendData = metrics.timeline_points || []

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

    return allDates.map((dayKey) => ({
      id: dayKey,
      title: formatGroupTitle(dayKey, todayKey, yesterdayKey),
      items: dateMap.get(dayKey) || [],
      total: metrics.daily_totals?.[dayKey] || 0,
      loaded: !!dateMap.get(dayKey)?.length,
    }))
  }, [isSearchMode, allDates, displayedRows, todayKey, yesterdayKey, metrics.daily_totals])

  const insightPanels = useMemo(
    () => [
      { key: 'trends' as InsightKey, title: '宏观技术趋势', icon: <TrendingUp size={16} color="#2dd4bf" />, items: normalizeInsightItems(Array.isArray(currentInsights?.trends) ? currentInsights.trends : []) },
      { key: 'weak_signals' as InsightKey, title: '暗流弱信号', icon: <Radio size={16} color="#f59e0b" />, items: normalizeInsightItems(Array.isArray(currentInsights?.weak_signals) ? currentInsights.weak_signals : []) },
      { key: 'daily_advices' as InsightKey, title: '今日行动建议', icon: <Lightbulb size={16} color="#a78bfa" />, items: normalizeInsightItems(Array.isArray(currentInsights?.daily_advices) ? currentInsights.daily_advices : []) },
    ],
    [currentInsights]
  )

  // KPI 使用服务端计算的完整数据
  const kpis = [
    { key: 'all', title: '有效信号', value: metrics.signals_total ?? 0, tone: 'var(--accent)', delta: null, onClick: () => { setFilter('all'); setTimeScope('all') } },
    { key: 'analyzed', title: '已分析', value: metrics.analyzed_total ?? 0, tone: '#34d399', delta: null, onClick: () => { setFilter('analyzed'); setTimeScope('all') } },
    { key: 'today', title: '今日新增', value: metrics.total_today ?? 0, tone: '#60a5fa', delta: formatKpiDelta(metrics.total_today ?? 0, metrics.total_yesterday ?? 0), onClick: () => { setFilter('all'); setTimeScope('today') } },
    { key: 'source', title: '活跃情报源', value: metrics.active_sources_total ?? 0, tone: '#a78bfa', delta: null, onClick: () => setSelectedSource(null) },
  ] as const

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
  }, [loadingMore, isSearchMode, searchHasMore, searchLoading, fetchSearchPage, searchPage, getTailVisibleGroupId, groupData, todayKey, loadMoreForGroup, nextUnloadedDate, loadGroupData])

  // Hook: 统一无限滚动（替换原来的 IO + scroll 双监听）
  useInfiniteScroll({
    rootRef: timelineRef,
    sentinelRef: loadMoreRef,
    onLoadMore: maybeLoadMore,
    loading: loadingMore,
    rootMargin: '0px 0px 240px 0px',
  })

  const clearAllFilters = () => {
    setSearch(''); setSelectedSource(null); setSelectedTag(null); setFilter('all'); setTimeScope('all')
  }

  const jumpToTodayGroup = useCallback(() => {
    if (isSearchMode) {
      setSearch('')
      return
    }

    const todayGroupRef = groupRefs.current[todayKey]
    if (todayGroupRef) {
      setCollapsedGroups((prev) => ({ ...prev, [todayKey]: false }))
      todayGroupRef.scrollIntoView({ behavior: 'smooth', block: 'start' })
      return
    }

    if (!groupData[todayKey]?.loaded && !groupData[todayKey]?.loading) {
      void loadGroupData(todayKey).then(() => {
        setCollapsedGroups((prev) => ({ ...prev, [todayKey]: false }))
        requestAnimationFrame(() => {
          groupRefs.current[todayKey]?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        })
      })
    }
  }, [isSearchMode, todayKey, groupData, loadGroupData])

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

  const setMessage = (type: 'success' | 'error', text: string) => {
    setActionMessage({ type, text })
    setTimeout(() => setActionMessage(null), 3200)
  }

  const copyInsightText = async (title: string, items: ParsedInsightItem[]) => {
    const text = `${title}\n\n${items
      .map((item, i) => `${i + 1}. ${item.title}${item.content ? `\n   ${item.content}` : ''}`)
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

  // Render

  return (
    <>
      <div className="dashboard-left">
        <div className="header-container" style={{ marginBottom: 18 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Logo size={40} />
              <h1 className="h1">RSS 信号控制台</h1>
            </div>
            <div className="muted" style={{ marginTop: 6, marginLeft: 52 }}>
              <span suppressHydrationWarning>最后更新：{formatGeneratedAt(metrics.generated_at)}</span>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div className="live-status">
              <span className="status-dot" />
              <span>批量分析结果</span>
            </div>
            <button className="filter-btn" onClick={() => downloadRowsAsJson(displayedRows.slice(0, 500), '当前筛选')}>
              <Download size={13} /> 导出 JSON
            </button>
          </div>
        </div>

        <section className="kpi">
          {kpis.map((item) => (
            <button key={item.key} className="glass kpi-card" onClick={item.onClick}>
              <div className="kpi-title">{item.title}</div>
              <div className="kpi-value" style={{ color: item.tone }}>
                <AnimatedNumber value={item.value} />
              </div>
              {item.delta && <div className={`kpi-delta ${item.delta.trend}`}>{item.delta.text}</div>}
            </button>
          ))}
        </section>

        <div ref={chartsTriggerRef}>
          {shouldLoadCharts ? (
            <ChartsSection
              trendData={trendData}
              sourceData={sourceData}
              selectedSource={selectedSource}
              onSelectSource={setSelectedSource}
              timeRange={timeRange}
              onTimeRangeChange={setTimeRange}
              insightHistory={insightsHistory}
              selectedInsightIdx={selectedInsightIdx}
              onSelectInsight={setSelectedInsightIdx}
            />
          ) : (
            <section className="charts-grid" style={{ marginBottom: 18 }}>
              <div className="glass chart-card chart-deferred-card">
                <div className="chart-deferred-title">趋势图按需加载</div>
                <p className="chart-deferred-copy">滚动到此区域时再加载图表脚本，以减少首屏 JS。</p>
                <button className="filter-btn" onClick={() => setShouldLoadCharts(true)}>立即加载图表</button>
              </div>
              <div className="glass chart-card chart-deferred-card">
                <div className="chart-deferred-title">来源分布图按需加载</div>
                <p className="chart-deferred-copy">你也可以点击按钮手动加载，不影响核心数据阅读。</p>
                <button className="filter-btn" onClick={() => setShouldLoadCharts(true)}>立即加载图表</button>
              </div>
            </section>
          )}
        </div>

        {actionMessage && (
          <div className={`action-message ${actionMessage.type === 'success' ? 'success' : 'error'}`}>
            {actionMessage.type === 'success' ? <Check size={14} /> : <AlertCircle size={14} />}
            <span>{actionMessage.text}</span>
          </div>
        )}

        {currentInsights && (
          <section className="insight-grid">
            {insightPanels
              .filter((panel) => panel.items.length > 0)
              .map((panel) => (
                <div key={panel.key} className="glass chart-card tertiary-card insight-panel-card">
                  <div className="insight-panel-head">
                    <h3 className="chart-title insight-panel-title" style={{ margin: 0 }}>{panel.icon} {panel.title}</h3>
                    <div className="insight-panel-actions">
                      <button className="filter-btn icon-only-btn" onClick={() => copyInsightText(panel.title, panel.items)} title="复制" aria-label="复制">
                        <Copy size={13} />
                      </button>
                    </div>
                  </div>
                  <div className="insight-panel-body">
                    <ul className="insight-list">
                      {panel.items.map((item, i) => (
                        <li key={`${panel.key}-${i}-${item.title}`}>
                          <div className="insight-item-title">{item.title}</div>
                          {item.content && <div className="insight-item-content">{item.content}</div>}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              ))}
          </section>
        )}
      </div>

      <div className="dashboard-right">
        <div className="controls-bar" style={{ borderBottom: '1px solid var(--panel-border)', paddingBottom: 14, marginBottom: 0, flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
            <h2 style={{ fontSize: '20px', margin: 0, fontWeight: 700 }}>实时情报流</h2>
            <div className="filter-btn" style={{ padding: '5px 10px', fontSize: 12, display: 'flex', alignItems: 'center', gap: 4, cursor: 'default' }}>
              <ArrowUpDown size={12} /> 按时间
            </div>
          </div>

          <div style={{ width: '100%', position: 'relative' }}>
            <Search size={16} color="#8aa3be" style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
            <input ref={searchRef} className="search-input search-input-primary" placeholder="搜索标题、来源、标签…（/ 或 Cmd/Ctrl+K）" value={search} onChange={(e) => setSearch(e.target.value)} />
            {search && (
              <button onClick={() => setSearch('')} style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: '#8aa3be', cursor: 'pointer', fontSize: 18, lineHeight: 1, padding: 0 }}>
                ×
              </button>
            )}
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center', width: '100%', flexWrap: 'wrap' }}>
            <Filter size={15} color="#8aa3be" />
            <button className={`filter-btn ${filter === 'all' ? 'active' : ''}`} onClick={() => setFilter('all')}>全量</button>
            <button className={`filter-btn ${filter === 'analyzed' ? 'active' : ''}`} onClick={() => setFilter('analyzed')}>已分析</button>
            <button className={`filter-btn ${timeScope === 'today' ? 'active' : ''}`} onClick={() => setTimeScope((prev) => (prev === 'today' ? 'all' : 'today'))}>今日</button>
            <button className="filter-btn" onClick={jumpToTodayGroup}>定位今天</button>
            <button className="filter-btn" onClick={() => downloadRowsAsJson(displayedRows.slice(0, 500), '当前筛选')}>
              <Download size={13} /> 导出
            </button>
            {selectedSource && <button className="filter-btn source-filter-active" onClick={() => setSelectedSource(null)}>{selectedSource === '__others__' ? '其他来源' : selectedSource} ×</button>}
            {selectedTag && <button className="filter-btn source-filter-active" onClick={() => setSelectedTag(null)}>#{selectedTag} ×</button>}
            {(search || selectedSource || selectedTag || timeScope === 'today' || filter === 'analyzed') && <button className="filter-btn" onClick={clearAllFilters}>清除</button>}
          </div>

          <div style={{ fontSize: 12, color: '#8aa3be', width: '100%' }}>
            共 <span style={{ color: '#2dd4bf', fontWeight: 600 }}>{displayedRows.length}</span>
            {isSearchMode && <span> / {searchTotal}</span>} 条结果
          </div>
        </div>

        <div className="timeline-container" ref={timelineRef}>
          <section className="timeline" style={{ marginTop: 12 }}>
            {displayedRows.length === 0 && (() => {
              const reason = search.trim() ? `「${search.trim()}」` : selectedTag ? `#${selectedTag}` : selectedSource ? `「${selectedSource === '__others__' ? '其他来源' : selectedSource}」` : null
              return (
                <div style={{ textAlign: 'center', padding: '60px 20px', color: '#8aa3be' }}>
                  <div style={{ fontSize: 40, marginBottom: 12, opacity: 0.4 }}>◎</div>
                  <div style={{ fontSize: 14 }}>{reason ? `${reason} 暂无匹配信号` : '暂无信号数据'}</div>
                  {reason && (
                    <button onClick={clearAllFilters} style={{ marginTop: 12, background: 'none', border: '1px solid #8aa3be', color: '#8aa3be', padding: '4px 12px', borderRadius: 20, cursor: 'pointer', fontSize: 13 }}>
                      清除所有筛选
                    </button>
                  )}
                </div>
              )
            })()}

            {groupedRows.map((group) => {
              const groupState = groupData[group.id]
              const isLoading = isSearchMode ? false : (groupState?.loading ?? false)
              const isLoaded = isSearchMode ? true : (groupState?.loaded ?? false)
              return (
              <div key={group.id} className="feed-group" ref={(el) => { groupRefs.current[group.id] = el }}>
                <button className="feed-group-head" onClick={() => {
                  // 如果分组未加载，点击时加载数据
                  if (!isSearchMode && !isLoaded && !isLoading) {
                    void loadGroupData(group.id)
                    setCollapsedGroups((prev) => ({ ...prev, [group.id]: false }))
                    return
                  }
                  setCollapsedGroups((prev) => ({ ...prev, [group.id]: !prev[group.id] }))
                }}>
                  <span className="feed-group-title">{group.title}</span>
                  <span className="feed-group-meta">{group.total} 条</span>
                  {collapsedGroups[group.id] ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                </button>
                {!collapsedGroups[group.id] && (
                  <div className="feed-group-body">
                    {isLoading && group.items.length === 0 && (
                      <div style={{ color: '#8aa3be', fontSize: 12, padding: '8px 2px 10px' }}>正在加载...</div>
                    )}
                    {group.items.map((row, idx) => {
                      const rowKey = row.id || `${row.url}|${row.time}|${row.title || 'untitled'}`
                      return (
                        <FeedCard
                          key={`${group.id}-${rowKey}-${idx}`}
                          row={row}
                          idx={idx}
                          groupId={group.id}
                          now={now}
                          hoveredRowKey={hoveredRowKey}
                          selectedTag={selectedTag}
                          onHoverEnter={openRowHover}
                          onHoverLeave={closeRowHover}
                          onTagClick={(tag) => setSelectedTag((prev) => (prev === tag ? null : tag))}
                        />
                      )
                    })}
                  </div>
                )}
              </div>
              )
            })}

            {/* 无限滚动触发器 */}
            <div ref={loadMoreRef} style={{ height: 1 }} />
            {searchLoading && isSearchMode && (
              <div style={{ textAlign: 'center', fontSize: 12, color: '#8aa3be', padding: '8px 0 14px' }}>
                正在检索全量数据...
              </div>
            )}
            {loadingMore && (
              <div style={{ textAlign: 'center', fontSize: 12, color: '#8aa3be', padding: '8px 0 14px' }}>
                正在加载更多...
              </div>
            )}
          </section>
        </div>
      </div>
    </>
  )
}
