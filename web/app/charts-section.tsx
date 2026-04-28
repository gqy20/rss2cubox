'use client'

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
  ReferenceLine,
} from 'recharts'
import { Radar, Zap } from 'lucide-react'
import { PIE_COLORS } from './utils'

type TrendPoint = { name: string; total: number; analyzed: number }
type SourcePoint = { name: string; value: number }

type Props = {
  trendData: TrendPoint[]
  sourceData: SourcePoint[]
  selectedSource: string | null
  onSelectSource: (source: string | null | ((prev: string | null) => string | null)) => void
  timeRange: '7d' | '30d'
  onTimeRangeChange: (range: '7d' | '30d') => void
  insightHistory?: InsightHistoryItem[]
  selectedInsightIdx: number
  onSelectInsight: (idx: number) => void
}

type InsightHistoryItem = {
  generated_at: string
  data: {
    trends?: string[]
    weak_signals?: string[]
    daily_advices?: string[]
  }
}

export default function ChartsSection({ trendData, sourceData, selectedSource, onSelectSource, timeRange, onTimeRangeChange, insightHistory, selectedInsightIdx, onSelectInsight }: Props) {
  return (
    <section className="charts-grid" style={{ marginBottom: 18 }}>
      <div className="glass chart-card">
        {/* 图表Header：标题 + 时间范围 + 信号时段 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <h3 className="chart-title" style={{ margin: 0 }}>
            <Zap size={18} color="#2dd4bf" /> 信号爆发趋势
          </h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {/* 7天/30天切换 - Apple风格pill toggle */}
            <div style={{ display: 'flex', background: 'rgba(255,255,255,0.05)', borderRadius: 8, padding: 2, gap: 2 }}>
              {(['7d', '30d'] as const).map((range) => (
                <button
                  key={range}
                  onClick={() => onTimeRangeChange(range)}
                  style={{
                    background: timeRange === range ? 'rgba(45, 212, 191, 0.2)' : 'transparent',
                    border: 'none',
                    borderRadius: 6,
                    color: timeRange === range ? 'var(--accent)' : '#8aa3be',
                    padding: '4px 10px',
                    fontSize: 12,
                    cursor: 'pointer',
                    transition: 'all 0.2s ease',
                    fontWeight: timeRange === range ? 600 : 400,
                  }}
                >
                  {range === '7d' ? '7天' : '30天'}
                </button>
              ))}
            </div>
            {/* 信号时段选择 - 仅在有多条历史时显示 */}
            {insightHistory && insightHistory.length > 1 && (
              <select
                value={selectedInsightIdx}
                onChange={(e) => onSelectInsight(Number(e.target.value))}
                style={{
                  background: 'rgba(255,255,255,0.04)',
                  border: '1px solid rgba(255,255,255,0.08)',
                  borderRadius: 6,
                  color: 'var(--accent)',
                  padding: '4px 8px',
                  fontSize: 11,
                  cursor: 'pointer',
                  minWidth: 100,
                }}
              >
                {insightHistory.map((item, idx) => (
                  <option key={item.generated_at} value={idx}>
                    {idx === 0 ? '最新信号' : new Date(item.generated_at).toLocaleString('zh-CN', {
                      month: '2-digit', day: '2-digit', hour: '2-digit', hour12: false,
                    })}
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>
        <div style={{ width: '100%', height: 250, marginTop: 14 }}>
          <ResponsiveContainer width="100%" height={250} minWidth={0} minHeight={250}>
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
              <Area type="monotone" dataKey="analyzed" name="已分析" stroke="#34d399" fillOpacity={1} fill="url(#colorHigh)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="glass chart-card">
        <h3 className="chart-title">
          <Radar size={18} color="#60a5fa" /> 情报源分布
        </h3>
        <div style={{ width: '100%', height: 250 }}>
          <ResponsiveContainer width="100%" height={250} minWidth={0} minHeight={250}>
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
                  if (src === '其他') {
                    onSelectSource((prev) => (prev === '__others__' ? null : '__others__'))
                    return
                  }
                  onSelectSource((prev) => (prev === src ? null : src))
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
  )
}
