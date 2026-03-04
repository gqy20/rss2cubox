'use client'

import { useState, useMemo } from 'react'
import { 
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell as PieCell, Legend, BarChart, Bar, Cell
} from 'recharts'
import { ExternalLink, Activity, Filter, Radar, Info, CheckCircle2, ChevronRight, Zap, Target } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

// Types
type Row = { id: string; title: string; url: string; source: string; time: string; score?: number; reason?: string; tags?: string[]; core_event?: string; hidden_signal?: string; actionable?: string }
type Metrics = {
  generated_at?: string
  updates_total?: number
  sources_total?: number
  top_sources?: Array<{ source: string; count: number }>
}

function formatTime(value: string): string {
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString('zh-CN', { 
    month: 'numeric', day: 'numeric', 
    hour: '2-digit', minute: '2-digit' 
  })
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

const SCORE_COLORS = { high: '#34d399', mid: '#60a5fa', low: '#9ca3af' }
const PIE_COLORS = ['#2dd4bf', '#60a5fa', '#818cf8', '#a78bfa', '#c084fc']

export default function DashboardClient({ rows, metrics }: { rows: Row[], metrics: Metrics }) {
  const [filter, setFilter] = useState<'all' | 'high'>('all')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Derived state
  const displayedRows = useMemo(() => {
    if (filter === 'high') return rows.filter(r => (r.score ?? 0) >= 0.85)
    return rows
  }, [rows, filter])

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

  // Chart Data: Score Distribution for Left Panel
  const scoreData = useMemo(() => {
    let high = 0, mid = 0, low = 0
    rows.forEach(r => {
      const s = r.score ?? 0
      if (s >= 0.85) high++
      else if (s >= 0.7) mid++
      else low++
    })
    return [
      { name: '高价值 (≥0.85)', value: high, color: SCORE_COLORS.high },
      { name: '普通 (0.7-0.85)', value: mid, color: SCORE_COLORS.mid },
      { name: '较低 (<0.7)', value: low, color: SCORE_COLORS.low },
    ]
  }, [rows])

  // Chart Data: Sources
  const sourceData = useMemo(() => {
    if (metrics.top_sources?.length) {
      return metrics.top_sources.map(s => ({ name: s.source, value: s.count }))
    }
    const counts: Record<string, number> = {}
    rows.forEach(r => counts[r.source] = (counts[r.source] || 0) + 1)
    return Object.entries(counts)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 5)
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
            <div className="kpi-title">总信号拦截</div>
            <div className="kpi-value">{metrics.updates_total ?? 0}</div>
          </article>
          <article className="glass kpi-card">
            <div className="kpi-title">活跃情报源</div>
            <div className="kpi-value" style={{ color: '#60a5fa' }}>{metrics.sources_total ?? 0}</div>
          </article>
          <article className="glass kpi-card">
            <div className="kpi-title">高含金量信号 (≥0.85)</div>
            <div className="kpi-value" style={{ color: '#34d399' }}>
              {rows.filter(r => (r.score ?? 0) >= 0.85).length}
            </div>
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
                  >
                    {sourceData.map((entry, index) => (
                      <PieCell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
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

        {/* Third chart block for dashboard layout balance */}
        <section className="glass chart-card" style={{ flex: 1, minHeight: 200 }}>
           <h3 className="chart-title"><Target size={18} color="#c084fc" /> 最新批次质量评估</h3>
           <div style={{ width: '100%', height: 'calc(100% - 40px)', minHeight: 200 }}>
             <ResponsiveContainer>
               <BarChart data={scoreData} margin={{ top: 20, right: 20, bottom: 20, left: -20 }} layout="vertical">
                 <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" horizontal={false} />
                 <XAxis type="number" stroke="#8aa3be" fontSize={12} tickLine={false} axisLine={false} />
                 <YAxis dataKey="name" type="category" stroke="#8aa3be" fontSize={12} tickLine={false} axisLine={false} width={120} />
                 <Tooltip 
                   cursor={{ fill: 'rgba(255,255,255,0.05)' }}
                   contentStyle={{ backgroundColor: 'rgba(13, 27, 42, 0.9)', border: '1px solid #1f3550', borderRadius: '8px' }} 
                 />
                 <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={30}>
                   {scoreData.map((entry, index) => (
                     <Cell key={`cell-${index}`} fill={entry.color} />
                   ))}
                 </Bar>
               </BarChart>
             </ResponsiveContainer>
           </div>
        </section>
      </div>

      <div className="dashboard-right">
        <div className="controls-bar" style={{ borderBottom: '1px solid var(--panel-border)', paddingBottom: 16, marginBottom: 0 }}>
          <h2 style={{ fontSize: '20px', margin: 0, fontWeight: 600 }}>实时高能情报轴</h2>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
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
          </div>
        </div>

        <div className="timeline-container">
          <section className="timeline" style={{ marginTop: 16 }}>
            {displayedRows.map((row, idx) => {
              const s = row.score ?? 0
              const isHigh = s >= 0.85
              const isMid = s >= 0.7 && s < 0.85
              const isExpanded = expandedId === row.id

              return (
                <motion.div 
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: idx * 0.03 }}
                  key={row.id} 
                  className="timeline-item"
                >
                  <div className="timeline-node">
                    <div className={`node-dot ${isHigh ? 'glow-green' : isMid ? 'glow-blue' : 'glow-gray'}`}></div>
                    <div className="node-time">{formatDay(row.time)}<br/>{formatShortTime(row.time)}</div>
                  </div>

                  <div className={`glass timeline-content ${isExpanded ? 'expanded' : ''}`} onClick={() => setExpandedId(isExpanded ? null : row.id)}>
                    <div className="t-header" style={{ flexDirection: 'column', gap: 6, alignItems: 'flex-start' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%', alignItems: 'center' }}>
                        <span className="source-badge">{row.source}</span>
                        <span className={`score-badge ${isHigh ? 'score-high' : isMid ? 'score-mid' : 'score-low'}`}>
                          0.{Math.round(s * 100)} Score
                        </span>
                      </div>
                      {row.tags && row.tags.length > 0 && (
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                          {row.tags.slice(0, 3).map((tag, i) => (
                            <span key={i} className="hashtag">#{tag}</span>
                          ))}
                        </div>
                      )}
                    </div>
                    
                    <h3 className="t-title" style={{ fontSize: 14, marginTop: 8 }}>
                      {row.hidden_signal || row.title}
                    </h3>

                    <AnimatePresence>
                      {isExpanded && (
                        <motion.div 
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          className="t-expanded-area"
                        >
                          {row.core_event && (
                            <div className="t-ai-box" style={{ padding: 12, marginBottom: 8, background: 'rgba(52, 211, 153, 0.05)', borderLeft: '2px solid #34d399' }}>
                              <div className="ai-label"><Info size={13} color="#34d399"/> 核心事件</div>
                              <p className="ai-text" style={{ fontSize: 13, color: '#e2e8f0' }}>{row.core_event}</p>
                            </div>
                          )}
                          
                          {row.actionable && (
                            <div className="t-ai-box" style={{ padding: 12, marginBottom: 12, background: 'rgba(250, 204, 21, 0.05)', borderLeft: '2px solid #facc15' }}>
                              <div className="ai-label"><Zap size={13} color="#facc15"/> 行动建议及影响</div>
                              <p className="ai-text" style={{ fontSize: 13, color: '#e2e8f0' }}>{row.actionable}</p>
                            </div>
                          )}

                          {row.reason && !row.core_event && (
                            <div className="t-ai-box" style={{ padding: 12, marginBottom: 12 }}>
                              <div className="ai-label"><CheckCircle2 size={13} color="#34d399"/> 分析理由</div>
                              <p className="ai-text" style={{ fontSize: 13 }}>{row.reason}</p>
                            </div>
                          )}
                          
                          <div className="t-actions">
                            <a href={row.url} target="_blank" rel="noreferrer" className="action-btn" onClick={e => e.stopPropagation()} style={{ fontSize: 12, padding: '6px 12px' }}>
                              阅读原文 <ChevronRight size={14} />
                            </a>
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                </motion.div>
              )
            })}
          </section>
        </div>
      </div>
    </>
  )
}
