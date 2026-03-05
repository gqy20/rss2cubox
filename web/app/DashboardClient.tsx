'use client'

import { useState, useMemo, useEffect, useRef } from 'react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell as PieCell,
  Legend,
} from 'recharts'
import {
  Filter,
  Radar,
  Zap,
  TrendingUp,
  Radio,
  Lightbulb,
  Search,
  ArrowUpDown,
  Copy,
  ChevronDown,
  ChevronUp,
  KeyRound,
  Check,
  AlertCircle,
  Send,
} from 'lucide-react'
import {
  Logo,
  AnimatedNumber,
  PIE_COLORS,
  getDayKey,
  formatAxisDay,
  formatGroupTitle,
  formatKpiDelta,
} from './utils'
import FeedCard from './FeedCard'
import { ExportModal, SettingsModal } from './Modals'
import type { Row, Metrics, GlobalInsights, InsightKey, ExportScope, PendingExport } from './types'

type Props = {
  initialRows: Row[]
  totalCount: number
  metrics: Metrics
  insights?: GlobalInsights | null
}

export default function DashboardClient({ initialRows, totalCount, metrics, insights }: Props) {
  const [rows, setRows] = useState<Row[]>(initialRows)
  const [hasMore, setHasMore] = useState(totalCount > initialRows.length)
  const [loadingMore, setLoadingMore] = useState(false)
  const [currentPage, setCurrentPage] = useState(1)
  const [filter, setFilter] = useState<'all' | 'high'>('all')
  const [timeScope, setTimeScope] = useState<'all' | 'today'>('all')
  const [selectedSource, setSelectedSource] = useState<string | null>(null)
  const [selectedTag, setSelectedTag] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState<'time' | 'score'>('time')

  const [hoveredRowKey, setHoveredRowKey] = useState<string | null>(null)
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({})
  const [insightCollapsed, setInsightCollapsed] = useState<Record<InsightKey, boolean>>({ trends: false, weak_signals: false, daily_advices: false })

  const [cuboxConfigured, setCuboxConfigured] = useState(false)
  const [cuboxKeyInput, setCuboxKeyInput] = useState('')
  const [cuboxFolder, setCuboxFolder] = useState('RSS Inbox')
  const [showSettingsModal, setShowSettingsModal] = useState(false)
  const [pendingExport, setPendingExport] = useState<PendingExport>(null)
  const [exportScope, setExportScope] = useState<ExportScope>('current')
  const [selectedExportKeys, setSelectedExportKeys] = useState<string[]>([])
  const [cuboxBusy, setCuboxBusy] = useState(false)
  const [actionMessage, setActionMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const [now, setNow] = useState<Date | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const timelineRef = useRef<HTMLDivElement>(null)
  const hoverCloseTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})

  // Side Effects

  useEffect(() => {
    setNow(new Date())
    const timer = setInterval(() => setNow(new Date()), 60000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    timelineRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
  }, [filter, timeScope, selectedSource, selectedTag, search, sortBy])

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
    const checkCuboxKey = async () => {
      try {
        const res = await fetch('/api/cubox/key', { method: 'GET' })
        if (!res.ok) return
        const data = (await res.json()) as { configured?: boolean }
        setCuboxConfigured(Boolean(data.configured))
      } catch {
        // noop
      }
    }
    void checkCuboxKey()
  }, [])

  // Derived State

  const todayKey = useMemo(() => getDayKey(now ?? new Date()), [now])
  const yesterdayKey = useMemo(() => {
    const d = new Date(now ?? new Date())
    d.setDate(d.getDate() - 1)
    return getDayKey(d)
  }, [now])

  const baselineStats = useMemo(() => {
    const current = new Date()
    const today = getDayKey(current)
    const yd = new Date(current)
    yd.setDate(current.getDate() - 1)
    const yesterday = getDayKey(yd)

    let totalToday = 0, totalYesterday = 0, highToday = 0, highYesterday = 0
    const sourceToday = new Set<string>()
    const sourceYesterday = new Set<string>()

    rows.forEach((r) => {
      const key = getDayKey(r.time)
      if (!key) return
      if (key === today) {
        totalToday++
        if ((r.score ?? 0) >= 0.85) highToday++
        sourceToday.add(r.source || 'unknown')
      }
      if (key === yesterday) {
        totalYesterday++
        if ((r.score ?? 0) >= 0.85) highYesterday++
        sourceYesterday.add(r.source || 'unknown')
      }
    })

    return {
      totalAll: rows.length,
      highAll: rows.filter((r) => (r.score ?? 0) >= 0.85).length,
      totalToday, totalYesterday, highToday, highYesterday,
      sourceToday: sourceToday.size,
      sourceYesterday: sourceYesterday.size,
      activeSources: new Set(rows.map((r) => r.source || 'unknown')).size,
    }
  }, [rows])

  const topSourceNames = useMemo(() => {
    const counts: Record<string, number> = {}
    rows.forEach((r) => { counts[r.source || 'unknown'] = (counts[r.source || 'unknown'] || 0) + 1 })
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([name]) => name)
  }, [rows])

  const displayedRows = useMemo(() => {
    let result = filter === 'high' ? rows.filter((r) => (r.score ?? 0) >= 0.85) : [...rows]
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
    if (search.trim()) {
      const kw = search.trim().toLowerCase()
      result = result.filter((r) =>
        (r.title || '').toLowerCase().includes(kw) ||
        (r.source || '').toLowerCase().includes(kw) ||
        (r.source_label || '').toLowerCase().includes(kw) ||
        (r.source_feed || '').toLowerCase().includes(kw) ||
        (r.hidden_signal || '').toLowerCase().includes(kw) ||
        (r.core_event || '').toLowerCase().includes(kw) ||
        (r.reason || '').toLowerCase().includes(kw) ||
        (r.actionable || '').toLowerCase().includes(kw) ||
        (r.url || '').toLowerCase().includes(kw) ||
        (r.tags || []).some((t) => t.toLowerCase().includes(kw))
      )
    }
    if (sortBy === 'score') return result.sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
    return result.sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime())
  }, [rows, filter, timeScope, selectedSource, selectedTag, search, sortBy, todayKey, topSourceNames])

  const trendData = useMemo(() => {
    const dayMap = new Map<string, { name: string; total: number; high: number }>()
    const base = new Date()
    base.setHours(0, 0, 0, 0)
    for (let i = 6; i >= 0; i--) {
      const d = new Date(base)
      d.setDate(base.getDate() - i)
      dayMap.set(getDayKey(d), { name: formatAxisDay(d), total: 0, high: 0 })
    }
    rows.forEach((r) => {
      const slot = dayMap.get(getDayKey(r.time))
      if (!slot) return
      slot.total++
      if ((r.score ?? 0) >= 0.85) slot.high++
    })
    return Array.from(dayMap.values())
  }, [rows])

  const sourceData = useMemo(() => {
    const counts: Record<string, number> = {}
    rows.forEach((r) => { counts[r.source || 'unknown'] = (counts[r.source || 'unknown'] || 0) + 1 })
    const rawData = Object.entries(counts).map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value)
    const top5 = rawData.slice(0, 5)
    const others = rawData.slice(5)
    if (others.length > 0) top5.push({ name: '其他', value: others.reduce((sum, item) => sum + item.value, 0) })
    return top5
  }, [rows])

  const groupedRows = useMemo(() => {
    const map = new Map<string, Row[]>()
    for (const row of displayedRows) {
      const key = getDayKey(row.time)
      if (!map.has(key)) map.set(key, [])
      map.get(key)?.push(row)
    }
    return Array.from(map.entries()).map(([dayKey, items]) => ({
      id: dayKey,
      title: formatGroupTitle(dayKey, todayKey, yesterdayKey),
      items,
    }))
  }, [displayedRows, todayKey, yesterdayKey])

  const insightPanels = useMemo(
    () => [
      { key: 'trends' as InsightKey, title: '宏观技术趋势', icon: <TrendingUp size={16} color="#2dd4bf" />, items: Array.isArray(insights?.trends) ? insights.trends : [] },
      { key: 'weak_signals' as InsightKey, title: '暗流弱信号', icon: <Radio size={16} color="#f59e0b" />, items: Array.isArray(insights?.weak_signals) ? insights.weak_signals : [] },
      { key: 'daily_advices' as InsightKey, title: '今日行动建议', icon: <Lightbulb size={16} color="#a78bfa" />, items: Array.isArray(insights?.daily_advices) ? insights.daily_advices : [] },
    ],
    [insights]
  )

  const kpis = [
    { key: 'all', title: '有效信号', value: baselineStats.totalAll, tone: 'var(--accent)', delta: formatKpiDelta(baselineStats.totalToday, baselineStats.totalYesterday), onClick: () => { setFilter('all'); setTimeScope('all') } },
    { key: 'high', title: '高价值 (≥0.85)', value: baselineStats.highAll, tone: '#34d399', delta: formatKpiDelta(baselineStats.highToday, baselineStats.highYesterday), onClick: () => { setFilter('high'); setTimeScope('all') } },
    { key: 'today', title: '今日新增', value: baselineStats.totalToday, tone: '#60a5fa', delta: formatKpiDelta(baselineStats.totalToday, baselineStats.totalYesterday), onClick: () => { setFilter('all'); setTimeScope('today') } },
    { key: 'source', title: '活跃情报源', value: baselineStats.activeSources, tone: '#a78bfa', delta: formatKpiDelta(baselineStats.sourceToday, baselineStats.sourceYesterday), onClick: () => setSelectedSource(null) },
  ] as const

  // Handlers

  const loadMore = async () => {
    if (loadingMore || !hasMore) return
    setLoadingMore(true)
    const nextPage = currentPage + 1
    try {
      const res = await fetch(`/api/signals?page=${nextPage}&limit=50`)
      const data = await res.json()
      if (data.data && data.data.length > 0) {
        setRows((prev) => [...prev, ...data.data])
        setCurrentPage(nextPage)
        setHasMore(data.hasMore)
      } else {
        setHasMore(false)
      }
    } catch (error) {
      console.error('Failed to load more:', error)
    } finally {
      setLoadingMore(false)
    }
  }

  const clearAllFilters = () => {
    setSearch(''); setSelectedSource(null); setSelectedTag(null); setFilter('all'); setTimeScope('all')
  }

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

  const saveCuboxKey = async () => {
    if (!cuboxKeyInput.trim()) { setMessage('error', '请输入 Cubox key 或完整 API URL'); return }
    setCuboxBusy(true)
    try {
      const res = await fetch('/api/cubox/key', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ key: cuboxKeyInput.trim() }),
      })
      if (!res.ok) {
        const data = (await res.json()) as { error?: string }
        throw new Error(data.error || '保存失败')
      }
      setCuboxConfigured(true); setCuboxKeyInput('')
      setMessage('success', 'Cubox key 已保存（HttpOnly cookie）')
    } catch (err) {
      setMessage('error', err instanceof Error ? err.message : '保存 key 失败')
    } finally {
      setCuboxBusy(false)
    }
  }

  const clearCuboxKey = async () => {
    setCuboxBusy(true)
    try {
      await fetch('/api/cubox/key', { method: 'DELETE' })
      setCuboxConfigured(false)
      setMessage('success', 'Cubox key 已清除')
    } catch {
      setMessage('error', '清除 Cubox key 失败')
    } finally {
      setCuboxBusy(false)
    }
  }

  const exportRowsToCubox = async (rowsToExport: Row[], label: string) => {
    if (rowsToExport.length === 0) { setMessage('error', `${label} 没有可导出的条目`); return }
    if (!cuboxConfigured) { setShowSettingsModal(true); setMessage('error', '请先配置 Cubox key'); return }
    setCuboxBusy(true)
    try {
      const payload = {
        folder: cuboxFolder,
        items: rowsToExport.slice(0, 100).map((r) => ({
          url: r.url,
          title: r.title || r.hidden_signal || 'RSS 信号',
          tags: Array.from(new Set([...(r.tags || []), label])).slice(0, 8),
        })),
      }
      const res = await fetch('/api/cubox/export', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const data = (await res.json()) as { success?: number; failed?: number; error?: string }
      if (!res.ok) throw new Error(data.error || '导出失败')
      setMessage('success', `${label} 链接已导出到 Cubox：成功 ${data.success ?? 0} 条`)
    } catch (err) {
      setMessage('error', err instanceof Error ? err.message : '导出到 Cubox 失败')
    } finally {
      setCuboxBusy(false)
    }
  }

  const openExportPreview = (rowsToExport: Row[], label: string) => {
    if (rowsToExport.length === 0) { setMessage('error', `${label} 没有可导出的条目`); return }
    const sliced = rowsToExport.slice(0, 100)
    setPendingExport({ label, rows: sliced })
    setSelectedExportKeys(sliced.map((r, idx) => `${r.id || r.url}|${r.time}|${idx}`))
  }

  const rowsForScope = (scope: ExportScope): { label: string; rows: Row[] } => {
    if (scope === 'high') return { label: '高价值', rows: displayedRows.filter((r) => (r.score ?? 0) >= 0.85) }
    if (scope === 'today') return { label: '今日', rows: displayedRows.filter((r) => getDayKey(r.time) === todayKey) }
    return { label: '当前筛选', rows: displayedRows }
  }

  const openExportByScope = (scope: ExportScope) => {
    setExportScope(scope)
    const resolved = rowsForScope(scope)
    openExportPreview(resolved.rows, resolved.label)
  }

  const updateExportScope = (scope: ExportScope) => {
    setExportScope(scope)
    const resolved = rowsForScope(scope)
    const sliced = resolved.rows.slice(0, 100)
    setPendingExport({ label: resolved.label, rows: sliced })
    setSelectedExportKeys(sliced.map((r, idx) => `${r.id || r.url}|${r.time}|${idx}`))
  }

  const copyInsightText = async (title: string, items: string[]) => {
    try {
      await navigator.clipboard.writeText(`${title}\n\n${items.map((item, i) => `${i + 1}. ${item}`).join('\n')}`)
      setMessage('success', `${title} 已复制`)
    } catch {
      setMessage('error', '复制失败')
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
              最后更新：{metrics.generated_at ? new Date(metrics.generated_at).toLocaleString('zh-CN') : '未知'}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div className="live-status">
              <span className="status-dot" />
              <span>实时分析中</span>
            </div>
            <button className="filter-btn" onClick={() => setShowSettingsModal(true)}>
              <KeyRound size={13} /> 设置
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
              <div className={`kpi-delta ${item.delta.trend}`}>{item.delta.text}</div>
            </button>
          ))}
        </section>

        <section className="charts-grid" style={{ marginBottom: 18 }}>
          <div className="glass chart-card">
            <h3 className="chart-title">
              <Zap size={18} color="#2dd4bf" /> 信号爆发趋势 (最近7天)
            </h3>
            <div style={{ width: '100%', height: 250, marginTop: 14 }}>
              <ResponsiveContainer>
                <AreaChart data={trendData} margin={{ top: 10, right: 8, left: -16, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorHigh" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#34d399" stopOpacity={0.7} />
                      <stop offset="95%" stopColor="#34d399" stopOpacity={0.03} />
                    </linearGradient>
                    <linearGradient id="colorTotal" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#60a5fa" stopOpacity={0.45} />
                      <stop offset="95%" stopColor="#60a5fa" stopOpacity={0.04} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                  <XAxis dataKey="name" stroke="#8aa3be" fontSize={12} tickLine={false} axisLine={false} />
                  <YAxis stroke="#8aa3be" fontSize={12} tickLine={false} axisLine={false} />
                  <Tooltip contentStyle={{ backgroundColor: 'rgba(13, 27, 42, 0.96)', border: '1px solid #1f3550', borderRadius: '8px', color: '#fff' }} itemStyle={{ color: '#e7edf5' }} />
                  <Legend verticalAlign="top" height={28} iconType="circle" wrapperStyle={{ fontSize: 12, color: '#8aa3be' }} />
                  <Area type="monotone" dataKey="total" name="总数" stroke="#60a5fa" fillOpacity={1} fill="url(#colorTotal)" />
                  <Area type="monotone" dataKey="high" name="优质" stroke="#34d399" fillOpacity={1} fill="url(#colorHigh)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="glass chart-card">
            <h3 className="chart-title">
              <Radar size={18} color="#60a5fa" /> 情报源分布
            </h3>
            <div style={{ width: '100%', height: 250 }}>
              <ResponsiveContainer>
                <PieChart>
                  <Pie
                    data={sourceData}
                    cx="50%"
                    cy="50%"
                    innerRadius={68}
                    outerRadius={88}
                    paddingAngle={4}
                    dataKey="value"
                    stroke="none"
                    style={{ cursor: 'pointer' }}
                    onClick={(_, index) => {
                      const src = sourceData[index]?.name
                      if (!src) return
                      if (src === '其他') { setSelectedSource((prev) => (prev === '__others__' ? null : '__others__')); return }
                      setSelectedSource((prev) => (prev === src ? null : src))
                    }}
                  >
                    {sourceData.map((entry, index) => {
                      const selectedName = selectedSource === '__others__' ? '其他' : selectedSource
                      const dimmed = Boolean(selectedName && entry.name !== selectedName)
                      return <PieCell key={`cell-${entry.name}`} fill={PIE_COLORS[index % PIE_COLORS.length]} opacity={dimmed ? 0.25 : 1} />
                    })}
                  </Pie>
                  <Tooltip contentStyle={{ backgroundColor: 'rgba(13, 27, 42, 0.96)', border: '1px solid #1f3550', borderRadius: '8px', color: '#fff' }} itemStyle={{ color: '#fff' }} />
                  <Legend verticalAlign="bottom" height={32} wrapperStyle={{ fontSize: 12, color: '#8aa3be' }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>

        {actionMessage && (
          <div className={`action-message ${actionMessage.type === 'success' ? 'success' : 'error'}`}>
            {actionMessage.type === 'success' ? <Check size={14} /> : <AlertCircle size={14} />}
            <span>{actionMessage.text}</span>
          </div>
        )}

        {insights && (
          <section className="insight-grid">
            {insightPanels
              .filter((panel) => panel.items.length > 0)
              .map((panel) => (
                <div key={panel.key} className="glass chart-card tertiary-card insight-panel-card">
                  <div className="insight-panel-head">
                    <h3 className="chart-title" style={{ margin: 0 }}>{panel.icon} {panel.title}</h3>
                    <div className="insight-panel-actions">
                      <button
                        className="filter-btn icon-only-btn"
                        onClick={() => setInsightCollapsed((prev) => ({ ...prev, [panel.key]: !prev[panel.key] }))}
                        title={insightCollapsed[panel.key] ? '展开' : '收起'}
                        aria-label={insightCollapsed[panel.key] ? '展开' : '收起'}
                      >
                        {insightCollapsed[panel.key] ? <ChevronDown size={13} /> : <ChevronUp size={13} />}
                      </button>
                      <button className="filter-btn icon-only-btn" onClick={() => copyInsightText(panel.title, panel.items)} title="复制" aria-label="复制">
                        <Copy size={13} />
                      </button>
                    </div>
                  </div>
                  {!insightCollapsed[panel.key] && (
                    <ul className="insight-list">
                      {panel.items.map((item, i) => <li key={i}>{item}</li>)}
                    </ul>
                  )}
                </div>
              ))}
          </section>
        )}
      </div>

      <div className="dashboard-right">
        <div className="controls-bar" style={{ borderBottom: '1px solid var(--panel-border)', paddingBottom: 14, marginBottom: 0, flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
            <h2 style={{ fontSize: '20px', margin: 0, fontWeight: 700 }}>实时情报流</h2>
            <button className="filter-btn" onClick={() => setSortBy((prev) => (prev === 'time' ? 'score' : 'time'))} style={{ padding: '5px 10px', fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
              <ArrowUpDown size={12} /> {sortBy === 'score' ? '按分数' : '按时间'}
            </button>
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
            <button className={`filter-btn ${filter === 'high' ? 'active' : ''}`} onClick={() => setFilter('high')}>高价值</button>
            <button className={`filter-btn ${timeScope === 'today' ? 'active' : ''}`} onClick={() => setTimeScope((prev) => (prev === 'today' ? 'all' : 'today'))}>今日</button>
            <button className="filter-btn" onClick={() => openExportByScope('current')} disabled={cuboxBusy}>
              <Send size={13} /> 导出
            </button>
            {selectedSource && <button className="filter-btn source-filter-active" onClick={() => setSelectedSource(null)}>{selectedSource === '__others__' ? '其他来源' : selectedSource} ×</button>}
            {selectedTag && <button className="filter-btn source-filter-active" onClick={() => setSelectedTag(null)}>#{selectedTag} ×</button>}
            {(search || selectedSource || selectedTag || timeScope === 'today' || filter === 'high') && <button className="filter-btn" onClick={clearAllFilters}>清除</button>}
          </div>

          <div style={{ fontSize: 12, color: '#8aa3be', width: '100%' }}>
            共 <span style={{ color: '#2dd4bf', fontWeight: 600 }}>{displayedRows.length}</span> 条结果
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

            {groupedRows.map((group) => (
              <div key={group.id} className="feed-group">
                <button className="feed-group-head" onClick={() => setCollapsedGroups((prev) => ({ ...prev, [group.id]: !prev[group.id] }))}>
                  <span className="feed-group-title">{group.title}</span>
                  <span className="feed-group-meta">{group.items.length} 条</span>
                  {collapsedGroups[group.id] ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                </button>
                {!collapsedGroups[group.id] && (
                  <div className="feed-group-body">
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
            ))}

            {hasMore && (
              <div style={{ display: 'flex', justifyContent: 'center', padding: '24px 0' }}>
                <button className="filter-btn active" onClick={loadMore} disabled={loadingMore} style={{ minWidth: 160 }}>
                  {loadingMore ? '加载中...' : `加载更多 (${totalCount - rows.length} 条)`}
                </button>
              </div>
            )}
          </section>
        </div>
      </div>

      <ExportModal
        pendingExport={pendingExport}
        onClose={() => setPendingExport(null)}
        selectedExportKeys={selectedExportKeys}
        setSelectedExportKeys={setSelectedExportKeys}
        exportScope={exportScope}
        cuboxBusy={cuboxBusy}
        onExportToCubox={exportRowsToCubox}
        onDownloadJson={downloadRowsAsJson}
        onUpdateExportScope={updateExportScope}
      />

      <SettingsModal
        show={showSettingsModal}
        onClose={() => setShowSettingsModal(false)}
        cuboxConfigured={cuboxConfigured}
        cuboxKeyInput={cuboxKeyInput}
        setCuboxKeyInput={setCuboxKeyInput}
        cuboxFolder={cuboxFolder}
        setCuboxFolder={setCuboxFolder}
        cuboxBusy={cuboxBusy}
        onSave={saveCuboxKey}
        onClear={clearCuboxKey}
      />
    </>
  )
}
