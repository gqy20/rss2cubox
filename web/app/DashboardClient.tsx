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
import { ExternalLink, Filter, Radar, Zap, TrendingUp, Radio, Lightbulb, Search, ArrowUpDown } from 'lucide-react'
import { motion } from 'framer-motion'

// Types
type Row = {
  id: string
  title: string
  url: string
  source: string
  time: string
  score?: number
  reason?: string
  tags?: string[]
  core_event?: string
  hidden_signal?: string
  actionable?: string
  source_feed?: string
  source_label?: string
  cover_url?: string
}
type Metrics = {
  generated_at?: string
  updates_total?: number
  sources_total?: number
  top_sources?: Array<{ source: string; count: number }>
}
type GlobalInsights = {
  generated_at?: string
  source_count?: number
  trends?: string[]
  weak_signals?: string[]
  daily_advices?: string[]
}

function formatRelativeTime(value: string, now: Date | null): string {
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  if (!now) return dt.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  const diff = now.getTime() - dt.getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins}分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}小时前`
  return `${Math.floor(hours / 24)}天前`
}

function formatShortTime(value: string): string {
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function getDayKey(value: string | Date): string {
  const dt = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(dt.getTime())) return ''
  const y = dt.getFullYear()
  const m = `${dt.getMonth() + 1}`.padStart(2, '0')
  const d = `${dt.getDate()}`.padStart(2, '0')
  return `${y}-${m}-${d}`
}

function formatAxisDay(value: Date): string {
  return value.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

function formatKpiDelta(current: number, previous: number): { text: string; trend: 'up' | 'down' | 'flat' } {
  const diff = current - previous
  if (diff === 0) return { text: '持平 vs 昨日', trend: 'flat' }
  if (previous <= 0) {
    return { text: `${diff > 0 ? '↑' : '↓'} ${diff > 0 ? '+' : ''}${diff} vs 昨日`, trend: diff > 0 ? 'up' : 'down' }
  }
  const percent = Math.round((Math.abs(diff) / previous) * 100)
  return {
    text: `${diff > 0 ? '↑' : '↓'} ${diff > 0 ? '+' : ''}${percent}% vs 昨日`,
    trend: diff > 0 ? 'up' : 'down',
  }
}

function Logo({ size = 36 }: { size?: number }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 64 64" fill="none">
      <defs>
        <linearGradient id="lg1" x1="0" y1="0" x2="64" y2="64" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#2dd4bf" />
          <stop offset="100%" stopColor="#60a5fa" />
        </linearGradient>
        <linearGradient id="lg2" x1="0" y1="0" x2="64" y2="64" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#2dd4bf" stopOpacity="0.12" />
          <stop offset="100%" stopColor="#60a5fa" stopOpacity="0.12" />
        </linearGradient>
      </defs>
      <circle cx="32" cy="32" r="31" fill="url(#lg2)" stroke="url(#lg1)" strokeWidth="1" />
      <path d="M 14 50 A 26 26 0 0 1 50 14" stroke="url(#lg1)" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M 18 50 A 18 18 0 0 1 50 18" stroke="url(#lg1)" strokeWidth="2.5" strokeLinecap="round" opacity="0.7" />
      <path d="M 22 50 A 10 10 0 0 1 50 22" stroke="url(#lg1)" strokeWidth="2.5" strokeLinecap="round" opacity="0.45" />
      <circle cx="14" cy="50" r="3.5" fill="url(#lg1)" />
      <circle cx="50" cy="14" r="2" fill="#60a5fa" opacity="0.9" />
    </svg>
  )
}

const PIE_COLORS = ['#2dd4bf', '#60a5fa', '#818cf8', '#a78bfa', '#c084fc']

function AnimatedNumber({ value }: { value: number }) {
  const [display, setDisplay] = useState(0)
  useEffect(() => {
    const duration = 900
    const startTime = performance.now()
    const update = (currentNow: number) => {
      const progress = Math.min((currentNow - startTime) / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(Math.round(value * eased))
      if (progress < 1) requestAnimationFrame(update)
    }
    requestAnimationFrame(update)
  }, [value])
  return <>{display}</>
}

function ScoreBar({ score }: { score: number }) {
  const color = score >= 0.85 ? '#34d399' : score >= 0.7 ? '#60a5fa' : '#9ca3af'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ width: 42, height: 4, background: 'rgba(255,255,255,0.08)', borderRadius: 4, overflow: 'hidden' }}>
        <div
          style={{
            width: `${Math.round(score * 100)}%`,
            height: '100%',
            background: color,
            borderRadius: 4,
          }}
        />
      </div>
      <span style={{ fontSize: 11, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>{score.toFixed(2)}</span>
    </div>
  )
}

export default function DashboardClient({ rows, metrics, insights }: { rows: Row[]; metrics: Metrics; insights?: GlobalInsights | null }) {
  const [filter, setFilter] = useState<'all' | 'high'>('all')
  const [timeScope, setTimeScope] = useState<'all' | 'today'>('all')
  const [selectedSource, setSelectedSource] = useState<string | null>(null)
  const [selectedTag, setSelectedTag] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState<'time' | 'score'>('time')
  const [hoveredRowKey, setHoveredRowKey] = useState<string | null>(null)
  const [now, setNow] = useState<Date | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const timelineRef = useRef<HTMLDivElement>(null)
  const hoverCloseTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})

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

  const todayKey = useMemo(() => getDayKey(now ?? new Date()), [now])

  const baselineStats = useMemo(() => {
    const current = new Date()
    const today = getDayKey(current)
    const yesterdayDate = new Date(current)
    yesterdayDate.setDate(current.getDate() - 1)
    const yesterday = getDayKey(yesterdayDate)

    let totalToday = 0
    let totalYesterday = 0
    let highToday = 0
    let highYesterday = 0
    const sourceToday = new Set<string>()
    const sourceYesterday = new Set<string>()

    rows.forEach((r) => {
      const key = getDayKey(r.time)
      if (!key) return
      if (key === today) {
        totalToday += 1
        if ((r.score ?? 0) >= 0.85) highToday += 1
        sourceToday.add(r.source || 'unknown')
      }
      if (key === yesterday) {
        totalYesterday += 1
        if ((r.score ?? 0) >= 0.85) highYesterday += 1
        sourceYesterday.add(r.source || 'unknown')
      }
    })

    const totalAll = rows.length
    const highAll = rows.filter((r) => (r.score ?? 0) >= 0.85).length

    return {
      totalAll,
      highAll,
      totalToday,
      totalYesterday,
      highToday,
      highYesterday,
      sourceToday: sourceToday.size,
      sourceYesterday: sourceYesterday.size,
      activeSources: new Set(rows.map((r) => r.source || 'unknown')).size,
    }
  }, [rows])

  const displayedRows = useMemo(() => {
    let result = filter === 'high' ? rows.filter((r) => (r.score ?? 0) >= 0.85) : [...rows]
    if (timeScope === 'today') result = result.filter((r) => getDayKey(r.time) === todayKey)
    if (selectedSource) result = result.filter((r) => r.source === selectedSource)
    if (selectedTag) result = result.filter((r) => (r.tags || []).includes(selectedTag))
    if (search.trim()) {
      const kw = search.trim().toLowerCase()
      result = result.filter(
        (r) =>
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
  }, [rows, filter, timeScope, selectedSource, selectedTag, search, sortBy, todayKey])

  const trendData = useMemo(() => {
    const dayMap = new Map<string, { name: string; total: number; high: number }>()
    const base = new Date()
    base.setHours(0, 0, 0, 0)

    for (let i = 6; i >= 0; i -= 1) {
      const d = new Date(base)
      d.setDate(base.getDate() - i)
      dayMap.set(getDayKey(d), { name: formatAxisDay(d), total: 0, high: 0 })
    }

    rows.forEach((r) => {
      const key = getDayKey(r.time)
      const slot = dayMap.get(key)
      if (!slot) return
      slot.total += 1
      if ((r.score ?? 0) >= 0.85) slot.high += 1
    })

    return Array.from(dayMap.values())
  }, [rows])

  const sourceData = useMemo(() => {
    const counts: Record<string, number> = {}
    rows.forEach((r) => {
      const source = r.source || 'unknown'
      counts[source] = (counts[source] || 0) + 1
    })

    const rawData = Object.entries(counts)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)

    const top5 = rawData.slice(0, 5)
    const others = rawData.slice(5)
    if (others.length > 0) {
      top5.push({ name: '其他', value: others.reduce((sum, item) => sum + item.value, 0) })
    }
    return top5
  }, [rows])

  const kpis = [
    {
      key: 'all',
      title: '有效信号',
      value: baselineStats.totalAll,
      tone: 'var(--accent)',
      delta: formatKpiDelta(baselineStats.totalToday, baselineStats.totalYesterday),
      onClick: () => {
        setFilter('all')
        setTimeScope('all')
      },
    },
    {
      key: 'high',
      title: '高价值 (≥0.85)',
      value: baselineStats.highAll,
      tone: '#34d399',
      delta: formatKpiDelta(baselineStats.highToday, baselineStats.highYesterday),
      onClick: () => {
        setFilter('high')
        setTimeScope('all')
      },
    },
    {
      key: 'today',
      title: '今日新增',
      value: baselineStats.totalToday,
      tone: '#60a5fa',
      delta: formatKpiDelta(baselineStats.totalToday, baselineStats.totalYesterday),
      onClick: () => {
        setFilter('all')
        setTimeScope('today')
      },
    },
    {
      key: 'source',
      title: '活跃情报源',
      value: baselineStats.activeSources,
      tone: '#a78bfa',
      delta: formatKpiDelta(baselineStats.sourceToday, baselineStats.sourceYesterday),
      onClick: () => {
        setSelectedSource(null)
      },
    },
  ] as const

  const clearAllFilters = () => {
    setSearch('')
    setSelectedSource(null)
    setSelectedTag(null)
    setFilter('all')
    setTimeScope('all')
  }

  const openRowHover = (key: string) => {
    const timer = hoverCloseTimers.current[key]
    if (timer) {
      clearTimeout(timer)
      delete hoverCloseTimers.current[key]
    }
    setHoveredRowKey(key)
  }

  const closeRowHover = (key: string) => {
    hoverCloseTimers.current[key] = setTimeout(() => {
      setHoveredRowKey((prev) => (prev === key ? null : prev))
      delete hoverCloseTimers.current[key]
    }, 140)
  }

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
          <div className="live-status">
            <span className="status-dot" />
            <span>实时分析中</span>
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

        <section className="glass cta-panel">
          <div className="cta-copy">
            <div className="cta-label">推荐工作流</div>
            <h3 style={{ margin: '2px 0 0', fontSize: 17 }}>先看高价值，再处理今日信号</h3>
            <p style={{ margin: '6px 0 0', fontSize: 13, color: 'var(--muted)' }}>
              当前可操作：高价值 {baselineStats.highAll} 条，今日新增 {baselineStats.totalToday} 条
            </p>
          </div>
          <div className="cta-actions">
            <button
              className="cta-btn"
              onClick={() => {
                setFilter('high')
                setTimeScope('all')
              }}
            >
              查看高价值 ({baselineStats.highAll})
            </button>
            <button
              className="cta-btn ghost"
              onClick={() => {
                setFilter('all')
                setTimeScope('today')
              }}
            >
              仅看今日 ({baselineStats.totalToday})
            </button>
            <a className="cta-btn ghost" href="/data/updates.json" target="_blank" rel="noreferrer">
              导出 JSON
            </a>
            <button className="cta-btn ghost" onClick={() => searchRef.current?.focus()}>
              聚焦搜索 (/)
            </button>
          </div>
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
                  <Tooltip
                    contentStyle={{ backgroundColor: 'rgba(13, 27, 42, 0.96)', border: '1px solid #1f3550', borderRadius: '8px', color: '#fff' }}
                    itemStyle={{ color: '#e7edf5' }}
                  />
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
                      if (!src || src === '其他') return
                      setSelectedSource((prev) => (prev === src ? null : src))
                    }}
                  >
                    {sourceData.map((entry, index) => (
                      <PieCell key={`cell-${entry.name}`} fill={PIE_COLORS[index % PIE_COLORS.length]} opacity={selectedSource && entry.name !== selectedSource ? 0.25 : 1} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ backgroundColor: 'rgba(13, 27, 42, 0.96)', border: '1px solid #1f3550', borderRadius: '8px', color: '#fff' }}
                    itemStyle={{ color: '#fff' }}
                  />
                  <Legend verticalAlign="bottom" height={32} wrapperStyle={{ fontSize: 12, color: '#8aa3be' }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>

        {insights && (
          <section className="insight-grid">
            {Array.isArray(insights.trends) && insights.trends.length > 0 && (
              <div className="glass chart-card tertiary-card">
                <h3 className="chart-title" style={{ marginBottom: 12 }}>
                  <TrendingUp size={16} color="#2dd4bf" /> 宏观技术趋势
                </h3>
                <ol style={{ margin: 0, padding: '0 0 0 18px', display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {insights.trends.map((t, i) => (
                    <li key={i} style={{ fontSize: 13, color: '#cbd5e1', lineHeight: 1.7 }}>
                      {t}
                    </li>
                  ))}
                </ol>
              </div>
            )}

            {Array.isArray(insights.weak_signals) && insights.weak_signals.length > 0 && (
              <div className="glass chart-card tertiary-card">
                <h3 className="chart-title" style={{ marginBottom: 12 }}>
                  <Radio size={16} color="#f59e0b" /> 暗流弱信号
                </h3>
                <ul style={{ margin: 0, padding: '0 0 0 18px', display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {insights.weak_signals.map((s, i) => (
                    <li key={i} style={{ fontSize: 13, color: '#cbd5e1', lineHeight: 1.7 }}>
                      {s}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {Array.isArray(insights.daily_advices) && insights.daily_advices.length > 0 && (
              <div className="glass chart-card tertiary-card">
                <h3 className="chart-title" style={{ marginBottom: 12 }}>
                  <Lightbulb size={16} color="#a78bfa" /> 今日行动建议
                </h3>
                <ul style={{ margin: 0, padding: '0 0 0 18px', display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {insights.daily_advices.map((a, i) => (
                    <li key={i} style={{ fontSize: 13, color: '#cbd5e1', lineHeight: 1.7 }}>
                      {a}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        )}
      </div>

      <div className="dashboard-right">
        <div className="controls-bar" style={{ borderBottom: '1px solid var(--panel-border)', paddingBottom: 14, marginBottom: 0, flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
            <h2 style={{ fontSize: '20px', margin: 0, fontWeight: 700 }}>实时情报流</h2>
            <button
              className="filter-btn"
              onClick={() => setSortBy((prev) => (prev === 'time' ? 'score' : 'time'))}
              style={{ padding: '5px 10px', fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}
              title="切换排序方式"
            >
              <ArrowUpDown size={12} /> {sortBy === 'score' ? '按分数' : '按时间'}
            </button>
          </div>

          <div style={{ width: '100%', position: 'relative' }}>
            <Search size={16} color="#8aa3be" style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
            <input
              ref={searchRef}
              className="search-input search-input-primary"
              placeholder="搜索标题、来源、标签…（/ 或 Cmd/Ctrl+K）"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {search && (
              <button
                onClick={() => setSearch('')}
                style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: '#8aa3be', cursor: 'pointer', fontSize: 18, lineHeight: 1, padding: 0 }}
              >
                ×
              </button>
            )}
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center', width: '100%', flexWrap: 'wrap' }}>
            <Filter size={15} color="#8aa3be" />
            <button className={`filter-btn ${filter === 'all' ? 'active' : ''}`} onClick={() => setFilter('all')}>
              全量
            </button>
            <button className={`filter-btn ${filter === 'high' ? 'active' : ''}`} onClick={() => setFilter('high')}>
              高价值
            </button>
            <button className={`filter-btn ${timeScope === 'today' ? 'active' : ''}`} onClick={() => setTimeScope((prev) => (prev === 'today' ? 'all' : 'today'))}>
              今日
            </button>
            {selectedSource && (
              <button className="filter-btn source-filter-active" onClick={() => setSelectedSource(null)}>
                {selectedSource} ×
              </button>
            )}
            {selectedTag && (
              <button className="filter-btn source-filter-active" onClick={() => setSelectedTag(null)}>
                #{selectedTag} ×
              </button>
            )}
            {(search || selectedSource || selectedTag || timeScope === 'today' || filter === 'high') && (
              <button className="filter-btn" onClick={clearAllFilters}>
                清除
              </button>
            )}
          </div>

          <div style={{ fontSize: 12, color: '#8aa3be', width: '100%' }}>
            共 <span style={{ color: '#2dd4bf', fontWeight: 600 }}>{displayedRows.length}</span> 条结果
          </div>
        </div>

        <div className="timeline-container" ref={timelineRef}>
          <section className="timeline" style={{ marginTop: 12 }}>
            {displayedRows.length === 0 && (() => {
              const reason = search.trim() ? `「${search.trim()}」` : selectedTag ? `#${selectedTag}` : selectedSource ? `「${selectedSource}」` : null
              return (
                <div style={{ textAlign: 'center', padding: '60px 20px', color: '#8aa3be' }}>
                  <div style={{ fontSize: 40, marginBottom: 12, opacity: 0.4 }}>◎</div>
                  <div style={{ fontSize: 14 }}>{reason ? `${reason} 暂无匹配信号` : '暂无信号数据'}</div>
                  {reason && (
                    <button
                      onClick={clearAllFilters}
                      style={{ marginTop: 12, background: 'none', border: '1px solid #8aa3be', color: '#8aa3be', padding: '4px 12px', borderRadius: 20, cursor: 'pointer', fontSize: 13 }}
                    >
                      清除所有筛选
                    </button>
                  )}
                </div>
              )
            })()}

            {displayedRows.map((row, idx) => {
              const s = row.score ?? 0
              const isHigh = s >= 0.85
              const isMid = s >= 0.7 && s < 0.85
              const rowKey = row.id || `${row.url}|${row.time}|${row.title || 'untitled'}`
              const isHovered = hoveredRowKey === rowKey
              const hasAiContent = Boolean(row.core_event || row.actionable || row.reason)

              return (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min(idx * 0.025, 0.2) }}
                  key={`${rowKey}-${idx}`}
                  className="timeline-item"
                >
                  <article
                    className={`glass timeline-content timeline-compact${isHigh ? ' timeline-high' : ''}${isHovered ? ' hover-open' : ''}`}
                    onMouseEnter={() => openRowHover(rowKey)}
                    onMouseLeave={() => closeRowHover(rowKey)}
                  >
                    <div className="t-header" style={{ marginBottom: 6 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                        <span className="source-badge">{row.source}</span>
                        <span className="node-time" title={`${row.time} ${formatShortTime(row.time)}`}>
                          {formatRelativeTime(row.time, now)}
                        </span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <ScoreBar score={s} />
                        <div className={`node-dot ${isHigh ? 'glow-green' : isMid ? 'glow-blue' : 'glow-gray'}`} />
                        <a href={row.url} target="_blank" rel="noreferrer" aria-label="打开原文" style={{ display: 'inline-flex', alignItems: 'center' }}>
                          <ExternalLink size={13} color="#8aa3be" />
                        </a>
                      </div>
                    </div>

                    <a href={row.url} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                      <h3 className="t-title">{row.title || row.hidden_signal || '未命名信号'}</h3>
                    </a>

                    {row.tags && row.tags.length > 0 && (
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6 }}>
                        {row.tags.slice(0, 3).map((tag, i) => (
                          <span
                            key={i}
                            className={`hashtag${selectedTag === tag ? ' hashtag-active' : ''}`}
                            onClick={(e) => {
                              e.preventDefault()
                              e.stopPropagation()
                              setSelectedTag((prev) => (prev === tag ? null : tag))
                            }}
                          >
                            #{tag}
                          </span>
                        ))}
                      </div>
                    )}

                    {!hasAiContent && (row.hidden_signal || row.core_event || row.actionable) && (
                      <p className="t-reason-preview t-reason-single" style={{ margin: 0 }}>
                        {row.hidden_signal || row.core_event || row.actionable}
                      </p>
                    )}

                    {hasAiContent && <p className="t-expand-hint">悬停查看 AI 分析</p>}

                    <div className={`t-ai-content${isHovered ? ' expanded' : ''}`}>
                      {row.core_event && (
                        <div className="t-ai-box" style={{ padding: 10, marginBottom: 8, background: 'rgba(52, 211, 153, 0.04)', borderLeft: '2px solid #34d399', borderRadius: '0 4px 4px 0' }}>
                          <p className="ai-text" style={{ fontSize: 13, color: '#e2e8f0', margin: 0 }}>
                            <strong style={{ color: '#34d399', marginRight: 6 }}>核心</strong>
                            {row.core_event}
                          </p>
                        </div>
                      )}

                      {row.actionable && (
                        <div className="t-ai-box" style={{ padding: 10, background: 'rgba(250, 204, 21, 0.04)', borderLeft: '2px solid #facc15', borderRadius: '0 4px 4px 0', marginBottom: row.reason ? 8 : 0 }}>
                          <p className="ai-text" style={{ fontSize: 13, color: '#e2e8f0', margin: 0 }}>
                            <strong style={{ color: '#facc15', marginRight: 6 }}>建议</strong>
                            {row.actionable}
                          </p>
                        </div>
                      )}

                      {row.reason && (
                        <div className="t-ai-box" style={{ padding: 10, background: 'rgba(96, 165, 250, 0.04)', borderLeft: '2px solid #60a5fa', borderRadius: '0 4px 4px 0' }}>
                          <p className="ai-text" style={{ fontSize: 13, color: '#e2e8f0', margin: 0 }}>
                            <strong style={{ color: '#60a5fa', marginRight: 6 }}>分析</strong>
                            {row.reason}
                          </p>
                        </div>
                      )}
                    </div>
                  </article>
                </motion.div>
              )
            })}
          </section>
        </div>
      </div>
    </>
  )
}
