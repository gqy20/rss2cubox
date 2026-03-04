'use client'

import { useState, useMemo, useEffect, useRef } from 'react'
import { 
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell as PieCell, Legend
} from 'recharts'
import { ExternalLink, Activity, Filter, Radar, Zap, TrendingUp, Radio, Lightbulb, Search, ArrowUpDown } from 'lucide-react'
import { motion } from 'framer-motion'

// Types
type Row = { id: string; title: string; url: string; source: string; time: string; score?: number; reason?: string; tags?: string[]; core_event?: string; hidden_signal?: string; actionable?: string }
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
  // Server render or before hydration: return absolute time to avoid mismatch
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
    hour: '2-digit', minute: '2-digit' 
  })
}

function formatDay(value: string): string {
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString('zh-CN', { month: 'short', day: 'numeric' })
}

const PIE_COLORS = ['#2dd4bf', '#60a5fa', '#818cf8', '#a78bfa', '#c084fc']

// KPI 数字滚动动画
function AnimatedNumber({ value }: { value: number }) {
  const [display, setDisplay] = useState(0)
  useEffect(() => {
    const duration = 900
    const startTime = performance.now()
    const update = (now: number) => {
      const progress = Math.min((now - startTime) / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(Math.round(value * eased))
      if (progress < 1) requestAnimationFrame(update)
    }
    requestAnimationFrame(update)
  }, [value])
  return <>{display}</>
}

// 分数进度条
function ScoreBar({ score }: { score: number }) {
  const color = score >= 0.85 ? '#34d399' : score >= 0.7 ? '#60a5fa' : '#9ca3af'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ width: 36, height: 3, background: 'rgba(255,255,255,0.08)', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{
          width: `${Math.round(score * 100)}%`, height: '100%',
          background: color, borderRadius: 2,
          boxShadow: score >= 0.85 ? `0 0 4px ${color}` : 'none'
        }} />
      </div>
      <span style={{ fontSize: 11, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums', letterSpacing: '0.02em' }}>{score.toFixed(2)}</span>
    </div>
  )
}

export default function DashboardClient({ rows, metrics, insights }: { rows: Row[], metrics: Metrics, insights?: GlobalInsights | null }) {
  const [filter, setFilter] = useState<'all' | 'high'>('all')
  const [selectedSource, setSelectedSource] = useState<string | null>(null)
  const [selectedTag, setSelectedTag] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState<'time' | 'score'>('time')
  const [now, setNow] = useState<Date | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setNow(new Date())
    const timer = setInterval(() => setNow(new Date()), 60000)
    return () => clearInterval(timer)
  }, [])

  // 键盘快捷键
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === '/' && document.activeElement?.tagName !== 'INPUT') {
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

  // Derived state
  const displayedRows = useMemo(() => {
    let result = filter === 'high' ? rows.filter(r => (r.score ?? 0) >= 0.85) : rows
    if (selectedSource) result = result.filter(r => r.source === selectedSource)
    if (selectedTag) result = result.filter(r => (r.tags || []).includes(selectedTag))
    if (search.trim()) {
      const kw = search.trim().toLowerCase()
      result = result.filter(r =>
        (r.title || '').toLowerCase().includes(kw) ||
        (r.hidden_signal || '').toLowerCase().includes(kw) ||
        (r.core_event || '').toLowerCase().includes(kw) ||
        (r.tags || []).some(t => t.toLowerCase().includes(kw))
      )
    }
    if (sortBy === 'score') result = [...result].sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
    return result
  }, [rows, filter, selectedSource, selectedTag, search, sortBy])

  // Chart Data: Time Series Area Chart
  const trendData = useMemo(() => {
    const dayCounts: Record<string, { name: string, total: number, high: number }> = {}
    
    // Reverse rows to go from oldest to newest for the chart timeline
    const sortedDesc = [...rows].sort((a,b) => new Date(a.time).getTime() - new Date(b.time).getTime())
    
    sortedDesc.forEach(r => {
      const day = formatDay(r.time)
      if (!dayCounts[day]) dayCounts[day] = { name: day, total: 0, high: 0 }
      dayCounts[day].total += 1
      if ((r.score ?? 0) >= 0.85) dayCounts[day].high += 1
    })
    
    return Object.values(dayCounts).slice(-7) // Last 7 days
  }, [rows])

  // Chart Data: Sources
  const sourceData = useMemo(() => {
    let rawData: Array<{ name: string; value: number }> = []
    if (metrics.top_sources?.length) {
      rawData = metrics.top_sources.map(s => ({ name: s.source, value: s.count }))
    } else {
      const counts: Record<string, number> = {}
      rows.forEach(r => counts[r.source] = (counts[r.source] || 0) + 1)
      rawData = Object.entries(counts)
        .map(([name, value]) => ({ name, value }))
        .sort((a, b) => b.value - a.value)
    }

    // 保留前5，其余合并为「其他」
    const top5 = rawData.slice(0, 5)
    const others = rawData.slice(5)
    if (others.length > 0) {
      const othersTotal = others.reduce((sum, item) => sum + item.value, 0)
      top5.push({ name: '其他', value: othersTotal })
    }
    return top5
  }, [metrics.top_sources, rows])

  return (
    <>
      <div className="dashboard-left">
        <div className="header-container" style={{ marginBottom: 24 }}>
          <div>
            <h1 className="h1">RSS 信号控制台</h1>
            <div className="muted">最后更新时间：{metrics.generated_at ? new Date(metrics.generated_at).toLocaleString('zh-CN') : '未知'}</div>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <div className="source-badge glow-pulse" style={{ backgroundColor: 'rgba(45, 212, 191, 0.2)', padding: '6px 12px' }}>
              <Activity size={14} color="#2dd4bf" /> <span style={{color: '#2dd4bf', fontWeight: 600}}>实时分析监控中</span>
            </div>
          </div>
        </div>

        <section className="kpi" style={{ marginBottom: 24 }}>
          <article className="glass kpi-card">
            <div className="kpi-title">有效信号</div>
            <div className="kpi-value"><AnimatedNumber value={rows.length} /></div>
          </article>
          <article className="glass kpi-card">
            <div className="kpi-title">高价值 (≥0.85)</div>
            <div className="kpi-value" style={{ color: '#34d399' }}><AnimatedNumber value={rows.filter(r => (r.score ?? 0) >= 0.85).length} /></div>
          </article>
          <article className="glass kpi-card">
            <div className="kpi-title">今日新增</div>
            <div className="kpi-value" style={{ color: '#60a5fa' }}>
              <AnimatedNumber value={rows.filter(r => {
                const d = new Date(r.time)
                const today = new Date()
                return d.getFullYear() === today.getFullYear() && d.getMonth() === today.getMonth() && d.getDate() === today.getDate()
              }).length} />
            </div>
          </article>
          <article className="glass kpi-card">
            <div className="kpi-title">活跃情报源</div>
            <div className="kpi-value" style={{ color: '#a78bfa' }}><AnimatedNumber value={metrics.sources_total ?? 0} /></div>
          </article>
        </section>

        <section className="charts-grid" style={{ marginBottom: 24 }}>
          <div className="glass chart-card">
            <h3 className="chart-title"><Zap size={18} color="#2dd4bf" /> 信号爆发强度趋势 (最近7天)</h3>
            <div style={{ width: '100%', height: 260, marginTop: 20 }}>
              <ResponsiveContainer>
                <AreaChart data={trendData} margin={{ top: 10, right: 30, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorHigh" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#34d399" stopOpacity={0.8}/>
                      <stop offset="95%" stopColor="#34d399" stopOpacity={0}/>
                    </linearGradient>
                    <linearGradient id="colorTotal" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#8aa3be" stopOpacity={0.3}/>
                      <stop offset="95%" stopColor="#8aa3be" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                  <XAxis dataKey="name" stroke="#8aa3be" fontSize={12} tickLine={false} axisLine={false} />
                  <YAxis stroke="#8aa3be" fontSize={12} tickLine={false} axisLine={false} />
                  <Tooltip 
                    contentStyle={{ backgroundColor: 'rgba(13, 27, 42, 0.9)', border: '1px solid #1f3550', borderRadius: '8px', color: '#fff' }} 
                    itemStyle={{ color: '#e7edf5' }}
                  />
                  <Legend verticalAlign="top" height={36} iconType="circle" wrapperStyle={{ fontSize: 12, color: '#8aa3be' }}/>
                  <Area type="monotone" dataKey="total" name="总截获" stroke="#8aa3be" fillOpacity={1} fill="url(#colorTotal)" />
                  <Area type="monotone" dataKey="high" name="优质信号" stroke="#34d399" fillOpacity={1} fill="url(#colorHigh)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="glass chart-card">
            <h3 className="chart-title"><Radar size={18} color="#60a5fa" /> 情报源活跃度</h3>
            <div style={{ width: '100%', height: 260 }}>
              <ResponsiveContainer>
                <PieChart>
                  <Pie
                    data={sourceData} cx="50%" cy="50%"
                    innerRadius={70} outerRadius={90}
                    paddingAngle={5} dataKey="value"
                    stroke="none"
                    style={{ cursor: 'pointer' }}
                    onClick={(_, index) => {
                      const src = sourceData[index]?.name
                      if (!src || src === '其他') return
                      setSelectedSource(prev => prev === src ? null : src)
                    }}
                  >
                    {sourceData.map((entry, index) => (
                      <PieCell
                        key={`cell-${index}`}
                        fill={PIE_COLORS[index % PIE_COLORS.length]}
                        opacity={selectedSource && entry.name !== selectedSource ? 0.25 : 1}
                      />
                    ))}
                  </Pie>
                  <Tooltip 
                    contentStyle={{ backgroundColor: 'rgba(13, 27, 42, 0.9)', border: '1px solid #1f3550', borderRadius: '8px', color: '#fff' }} 
                    itemStyle={{ color: '#fff' }}
                  />
                  <Legend verticalAlign="bottom" height={36} wrapperStyle={{ fontSize: 12, color: '#8aa3be' }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>

        {insights && (
          <section style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 8 }}>
            {Array.isArray(insights.trends) && insights.trends.length > 0 && (
              <div className="glass chart-card" style={{ padding: '16px 20px' }}>
                <h3 className="chart-title" style={{ marginBottom: 12 }}>
                  <TrendingUp size={16} color="#2dd4bf" /> 宏观技术趋势
                </h3>
                <ol style={{ margin: 0, padding: '0 0 0 18px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {insights.trends.map((t, i) => (
                    <li key={i} style={{ fontSize: 13, color: '#cbd5e1', lineHeight: 1.6 }}>{t}</li>
                  ))}
                </ol>
              </div>
            )}

            {Array.isArray(insights.weak_signals) && insights.weak_signals.length > 0 && (
              <div className="glass chart-card" style={{ padding: '16px 20px' }}>
                <h3 className="chart-title" style={{ marginBottom: 12 }}>
                  <Radio size={16} color="#f59e0b" /> 暗流弱信号
                </h3>
                <ul style={{ margin: 0, padding: '0 0 0 18px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {insights.weak_signals.map((s, i) => (
                    <li key={i} style={{ fontSize: 13, color: '#cbd5e1', lineHeight: 1.6 }}>{s}</li>
                  ))}
                </ul>
              </div>
            )}

            {Array.isArray(insights.daily_advices) && insights.daily_advices.length > 0 && (
              <div className="glass chart-card" style={{ padding: '16px 20px' }}>
                <h3 className="chart-title" style={{ marginBottom: 12 }}>
                  <Lightbulb size={16} color="#a78bfa" /> 今日行动建议
                </h3>
                <ul style={{ margin: 0, padding: '0 0 0 18px', display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {insights.daily_advices.map((a, i) => (
                    <li key={i} style={{ fontSize: 13, color: '#cbd5e1', lineHeight: 1.6 }}>{a}</li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        )}
      </div>

      <div className="dashboard-right">
        <div className="controls-bar" style={{ borderBottom: '1px solid var(--panel-border)', paddingBottom: 16, marginBottom: 0, flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
            <h2 style={{ fontSize: '20px', margin: 0, fontWeight: 600 }}>实时高能情报轴</h2>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
              <Filter size={16} color="#8aa3be" />
              <button 
                className={`filter-btn ${filter === 'all' ? 'active' : ''}`}
                onClick={() => setFilter('all')}
                style={{ padding: '4px 10px', fontSize: 13 }}
              >全量</button>
              <button 
                className={`filter-btn ${filter === 'high' ? 'active' : ''}`}
                onClick={() => setFilter('high')}
                style={{ padding: '4px 10px', fontSize: 13 }}
              >高价值</button>
              {selectedSource && (
                <button
                  className="filter-btn source-filter-active"
                  onClick={() => setSelectedSource(null)}
                  style={{ padding: '4px 10px', fontSize: 13, display: 'flex', alignItems: 'center', gap: 4 }}
                  title="点击清除数据源筛选"
                >
                  <span style={{ maxWidth: 100, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{selectedSource}</span>
                  <span style={{ fontSize: 16, lineHeight: 1 }}>×</span>
                </button>
              )}
              {selectedTag && (
                <button
                  className="filter-btn source-filter-active"
                  onClick={() => setSelectedTag(null)}
                  style={{ padding: '4px 10px', fontSize: 13, display: 'flex', alignItems: 'center', gap: 4 }}
                >
                  <span>#{selectedTag}</span>
                  <span style={{ fontSize: 16, lineHeight: 1 }}>×</span>
                </button>
              )}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', width: '100%' }}>
            <div style={{ flex: 1, position: 'relative' }}>
              <Search size={13} color="#8aa3be" style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
              <input
                ref={searchRef}
                className="search-input"
                placeholder="搜索标题、标签、AI分析…  [按 / 聚焦]"
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
              {search && (
                <button onClick={() => setSearch('')} style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: '#8aa3be', cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 0 }}>×</button>
              )}
            </div>
            <button
              className={`filter-btn ${sortBy === 'score' ? 'active' : ''}`}
              onClick={() => setSortBy(prev => prev === 'time' ? 'score' : 'time')}
              style={{ padding: '4px 10px', fontSize: 13, display: 'flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap' }}
              title="切换排序方式"
            >
              <ArrowUpDown size={12} />{sortBy === 'score' ? '按分数' : '按时间'}
            </button>
          </div>
          {(search || selectedSource || selectedTag) && (
            <div style={{ fontSize: 12, color: '#8aa3be' }}>
              共 <span style={{ color: '#2dd4bf', fontWeight: 600 }}>{displayedRows.length}</span> 条结果
            </div>
          )}
        </div>

        <div className="timeline-container">
          <section className="timeline" style={{ marginTop: 16 }}>
            {displayedRows.length === 0 && (
              <div style={{ textAlign: 'center', padding: '60px 20px', color: '#8aa3be' }}>
                <div style={{ fontSize: 40, marginBottom: 12, opacity: 0.4 }}>◎</div>
                <div style={{ fontSize: 14 }}>{selectedSource ? `「${selectedSource}」暂无匹配信号` : '暂无信号数据'}</div>
                {selectedSource && (
                  <button
                    onClick={() => setSelectedSource(null)}
                    style={{ marginTop: 12, background: 'none', border: '1px solid #8aa3be', color: '#8aa3be', padding: '4px 12px', borderRadius: 20, cursor: 'pointer', fontSize: 13 }}
                  >清除筛选</button>
                )}
              </div>
            )}
            {displayedRows.map((row, idx) => {
              const s = row.score ?? 0
              const isHigh = s >= 0.85
              const isMid = s >= 0.7 && s < 0.85

              return (
                <motion.div 
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: idx * 0.03 }}
                  key={`${row.id || row.url}-${row.time}-${idx}`} 
                  className="timeline-item"
                >
                  <div className="timeline-node">
                    <div className={`node-dot ${isHigh ? 'glow-green' : isMid ? 'glow-blue' : 'glow-gray'}`}></div>
                    <div className="node-time">
                      <span title={formatDay(row.time) + ' ' + formatShortTime(row.time)}>{formatRelativeTime(row.time, now)}</span>
                    </div>
                  </div>

                  <a 
                    href={row.url} 
                    target="_blank" 
                    rel="noreferrer"
                    className="glass timeline-content hover-scale" 
                    style={{ display: 'block', textDecoration: 'none', cursor: 'pointer' }}
                  >
                    <div className="t-header" style={{ flexDirection: 'column', gap: 6, alignItems: 'flex-start' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%', alignItems: 'center' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span className="source-badge">{row.source}</span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <ScoreBar score={s} />
                          <ExternalLink size={14} color="#8aa3be" />
                        </div>
                      </div>
                      {row.tags && row.tags.length > 0 && (
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                          {row.tags.slice(0, 3).map((tag, i) => (
                            <span
                              key={i}
                              className={`hashtag${selectedTag === tag ? ' hashtag-active' : ''}`}
                              onClick={e => { e.preventDefault(); e.stopPropagation(); setSelectedTag(prev => prev === tag ? null : tag) }}
                            >#{tag}</span>
                          ))}
                        </div>
                      )}
                    </div>
                    
                    <h3 className="t-title" style={{ fontSize: 14, marginTop: 8, color: '#f8fafc', fontWeight: 600 }}>
                      {row.hidden_signal || row.title}
                    </h3>

                    {(row.core_event || row.actionable || row.reason) && (
                      <p className="t-expand-hint">悬停查看AI分析 ↓</p>
                    )}

                    <div className="t-ai-content">
                      {row.core_event && (
                        <div className="t-ai-box" style={{ padding: 10, marginBottom: 8, background: 'rgba(52, 211, 153, 0.05)', borderLeft: '2px solid #34d399', borderRadius: '0 4px 4px 0' }}>
                          <p className="ai-text" style={{ fontSize: 13, color: '#e2e8f0', margin: 0 }}>
                            <strong style={{color: '#34d399', marginRight: 6}}>核心</strong>{row.core_event}
                          </p>
                        </div>
                      )}
                      
                      {row.actionable && (
                        <div className="t-ai-box" style={{ padding: 10, background: 'rgba(250, 204, 21, 0.05)', borderLeft: '2px solid #facc15', borderRadius: '0 4px 4px 0' }}>
                          <p className="ai-text" style={{ fontSize: 13, color: '#e2e8f0', margin: 0 }}>
                            <strong style={{color: '#facc15', marginRight: 6}}>建议</strong>{row.actionable}
                          </p>
                        </div>
                      )}

                      {row.reason && !row.core_event && (
                        <div className="t-ai-box" style={{ padding: 10, background: 'rgba(96, 165, 250, 0.05)', borderLeft: '2px solid #60a5fa', borderRadius: '0 4px 4px 0' }}>
                          <p className="ai-text" style={{ fontSize: 13, color: '#e2e8f0', margin: 0 }}>
                            <strong style={{color: '#60a5fa', marginRight: 6}}>分析</strong>{row.reason}
                          </p>
                        </div>
                      )}
                    </div>
                  </a>
                </motion.div>
              )
            })}
          </section>
        </div>
      </div>
    </>
  )
}
