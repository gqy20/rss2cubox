'use client'

import { useState, useMemo, useEffect, useRef, useCallback } from 'react'
import { useSearch } from '../hooks/useSearch'
import { useGroupData } from '../hooks/useGroupData'
import { useInfiniteScroll } from '../hooks/useInfiniteScroll'
import { useDashboardMetrics } from '../hooks/useDashboardMetrics'
import { useInsightPanels } from '../hooks/useInsightPanels'
import { useFilterState } from '../hooks/useFilterState'
import { useRowInteraction } from '../hooks/useRowInteraction'
import dynamic from 'next/dynamic'
import {
  Download,
} from 'lucide-react'
import {
  getDayKey,
  formatGroupTitle,
  formatKpiDelta,
  hasAiSummary,
} from './utils'
import type { Row, Metrics, GlobalInsights } from './types'
import { DashboardLeft, DashboardRight, type KpiItem, type ParsedInsightItem } from './DashboardSections'

type ChartsSectionProps = {
  trendData: Array<{ name: string; total: number; analyzed: number }>
  sourceData: Array<{ name: string; value: number }>
  selectedSource: string | null
  onSelectSource: (source: string | null | ((prev: string | null) => string | null)) => void
  onDateClick?: (dayKey: string) => void
  timeRange: '7d' | '30d'
  onTimeRangeChange: (range: '7d' | '30d') => void
  insightHistory?: import('../lib/signalStore').InsightHistoryItem[]
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

export default function DashboardClient({ initialRows, metrics: initialMetrics, insights, serverTime }: Props) {
  // ── Hook: 指标数据 + 时间 + 自动刷新 ──
  const {
    metrics, setMetrics, now, todayKey, yesterdayKey,
    formatGeneratedAt, refreshDashboardData,
  } = useDashboardMetrics({ initialMetrics, serverTime })

  // ── Hook: 洞察面板状态管理 ──
  const {
    insightPanels, visibleInsightPanels, activeInsightPanel,
    selectedInsightKey, setSelectedInsightKey,
    selectedInsightIdx, setSelectedInsightIdx,
  } = useInsightPanels({ insights: insights as any })

  // ── Hook: 筛选状态聚合 ──
  const {
    filter, setFilter,
    selectedSource, setSelectedSource,
    selectedTag, setSelectedTag,
    selectedDateKey, setSelectedDateKey,
    collapsedGroups, setCollapsedGroups,
    dateMenuOpen, setDateMenuOpen,
    dateQuery, setDateQuery,
    loadingMore, setLoadingMore,
    clearAllFilters,
  } = useFilterState()

  // ── Hook: 行交互（hover 展开/收起）──
  const {
    hoveredRowKey,
    onHoverEnter, onHoverLeave, onToggleOpen,
  } = useRowInteraction()

  // ── Hook: 搜索状态管理 ──
  const { search, searchRows, searchPage, searchTotal, searchHasMore, searchLoading, isSearchMode, setSearch, fetchSearchPage } = useSearch()

  // ── 分组数据状态（组件拥有，支持 SSR props 初始化）──
  const [groupData, setGroupData] = useState<Record<string, { loading: boolean; loaded: boolean; items: Row[]; hasMore: boolean }>>({})
  const [groupPaging, setGroupPaging] = useState<Record<string, { page: number }>>({})
  const allDates = useMemo(() => Object.keys(metrics.daily_totals || {}).sort((a, b) => b.localeCompare(a)), [metrics.daily_totals])

  const { loadGroupData, loadMoreForGroup, nextUnloadedDate } = useGroupData({ groupData, setGroupData, groupPaging, setGroupPaging, allDates })

  // ── UI 状态 ──
  const [actionMessage, setActionMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [shouldLoadCharts, setShouldLoadCharts] = useState(false)
  const [timeRange, setTimeRange] = useState<'7d' | '30d'>('7d')

  // ── Refs ──
  const searchRef = useRef<HTMLInputElement>(null)
  const chartsTriggerRef = useRef<HTMLDivElement>(null)
  const timelineRef = useRef<HTMLDivElement>(null)
  const loadMoreRef = useRef<HTMLDivElement>(null)
  const groupRefs = useRef<Record<string, HTMLDivElement | null>>({})

  // ── 初始化：只加载今天的数据 ──
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
      },
    })
    setGroupPaging({ [today]: { page: 1 } })
  }, [initialRows, initialMetrics.daily_totals])

  // ── 定时刷新今日行数据（与 metrics 刷新独立）──
  const refreshTodayRows = useCallback(async () => {
    try {
      const res = await fetch(`/api/signals?page=1&limit=50&date=${todayKey}`, { cache: 'no-store' })
      if (res.ok) {
        const payload = await res.json() as { data?: Row[]; hasMore?: boolean }
        if (Array.isArray(payload.data)) {
          setGroupData((prev) => ({
            ...prev,
            [todayKey]: { loading: false, loaded: true, items: payload.data!, hasMore: Boolean(payload.hasMore) },
          }))
          setGroupPaging((prev) => ({ ...prev, [todayKey]: { page: 1 } }))
        }
      }
    } catch (error) {
      console.error('Failed to refresh today rows:', error)
    }
  }, [todayKey])

  useEffect(() => {
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') void refreshTodayRows()
    }, 60_000)
    return () => clearInterval(timer)
  }, [refreshTodayRows])

  // ── 筛选变化时滚动到顶部 ──
  useEffect(() => {
    timelineRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
  }, [filter, selectedSource, selectedTag, search])

  // ── 全局键盘快捷键 ──
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
  }, [setSearch])

  // ── 图表懒加载（IntersectionObserver）──
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

  // ── Derived State ──

  const loadedRows = useMemo(() => {
    const allItems: Row[] = []
    Object.values(groupData).forEach((group) => {
      if (group.loaded) allItems.push(...group.items)
    })
    return allItems
  }, [groupData])

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
  }, [isSearchMode, searchRows, loadedRows, filter, selectedDateKey, selectedSource, selectedTag])

  const topSourceNames = useMemo(() => {
    const sources = metrics.top_source_counts || []
    return sources.slice(0, 5).map((s: { source: string }) => s.source)
  }, [metrics.top_source_counts])

  const trendData = useMemo(() => {
    const points = metrics.timeline_points || []
    const sliced = points.slice(timeRange === '7d' ? -7 : -30)
    const baseDate = new Date()
    baseDate.setHours(0, 0, 0, 0)
    return sliced.map((pt, i) => {
      if ('dayKey' in pt && pt.dayKey) return pt
      const d = new Date(baseDate)
      d.setDate(baseDate.getDate() - (sliced.length - 1 - i))
      const dk = getDayKey(d)
      return { ...pt, dayKey: dk }
    })
  }, [metrics.timeline_points, timeRange])

  const sourceData = useMemo(() => {
    const topSources = metrics.top_source_counts || []
    const rawData = topSources.map((s: { source: string; count: number }) => ({ name: s.source, value: s.count }))
    const top5 = rawData.slice(0, 5)
    const others = rawData.slice(5)
    if (others.length > 0) top5.push({ name: '其他', value: others.reduce((sum, item) => sum + item.value, 0) })
    return top5
  }, [metrics.top_source_counts])

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

  // ── KPI 数据 ──
  const kpis: KpiItem[] = [
    { key: 'all', title: '有效信号', value: metrics.signals_total ?? 0, tone: 'var(--accent)', delta: null, onClick: () => { setFilter('all'); setSelectedDateKey(null) } },
    { key: 'analyzed', title: '已分析', value: metrics.analyzed_total ?? 0, tone: '#34d399', delta: null, onClick: () => { setFilter('analyzed'); setSelectedDateKey(null) } },
    { key: 'today', title: '今日新增', value: metrics.total_today ?? 0, tone: '#60a5fa', delta: formatKpiDelta(metrics.total_today ?? 0, metrics.total_yesterday ?? 0), onClick: () => { setFilter('all'); setSelectedDateKey(todayKey); setCollapsedGroups((prev) => ({ ...prev, [todayKey]: false })); void loadGroupData(todayKey); timelineRef.current?.scrollTo({ top: 0, behavior: 'smooth' }) } },
    { key: 'source', title: '活跃情报源', value: metrics.active_sources_total ?? 0, tone: '#a78bfa', delta: null, onClick: () => setSelectedSource(null) },
  ]

  // ── Handlers ──

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
        return
      }
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

  useInfiniteScroll({
    rootRef: timelineRef,
    sentinelRef: loadMoreRef,
    onLoadMore: maybeLoadMore,
    loading: loadingMore,
    rootMargin: '0px 0px 240px 0px',
  })

  const jumpToDateGroup = useCallback((dayKey: string) => {
    if (!dayKey) return
    if (isSearchMode) setSearch('')
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
              insightHistory={[]}
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
        onClearAll={() => clearAllFilters(setSearch)}
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
        onHoverEnter={onHoverEnter}
        onHoverLeave={onHoverLeave}
        onToggleOpen={onToggleOpen}
        onTagClick={(tag) => setSelectedTag((prev) => (prev === tag ? null : tag))}
        searchLoading={searchLoading}
        loadingMore={loadingMore}
      />
    </>
  )
}
