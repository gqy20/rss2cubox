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
} from 'recharts'
import { Radar, Zap } from 'lucide-react'
import { PIE_COLORS } from './utils'

type TrendPoint = { name: string; total: number; high: number }
type SourcePoint = { name: string; value: number }

type Props = {
  trendData: TrendPoint[]
  sourceData: SourcePoint[]
  selectedSource: string | null
  onSelectSource: (source: string | null | ((prev: string | null) => string | null)) => void
}

export default function ChartsSection({ trendData, sourceData, selectedSource, onSelectSource }: Props) {
  return (
    <section className="charts-grid" style={{ marginBottom: 18 }}>
      <div className="glass chart-card">
        <h3 className="chart-title">
          <Zap size={18} color="#2dd4bf" /> 信号爆发趋势 (最近7天)
        </h3>
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
