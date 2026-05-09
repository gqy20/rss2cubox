'use client'

import { useMemo, useState } from 'react'
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
import { MenuPanel, PopoverMenu, SegmentedControl } from './ui'
import type { InsightHistoryItem } from '../lib/signalStore'

type TrendPoint = { name: string; dayKey?: string; total: number; analyzed: number }
type SourcePoint = { name: string; value: number }

type Props = {
  trendData: TrendPoint[]
  sourceData: SourcePoint[]
  selectedSource: string | null
  onSelectSource: (source: string | null | ((prev: string | null) => string | null)) => void
  onDateClick?: (dayKey: string) => void
  timeRange: '7d' | '30d'
  onTimeRangeChange: (range: '7d' | '30d') => void
  insightHistory?: InsightHistoryItem[]
  selectedInsightIdx: number
  onSelectInsight: (idx: number) => void
}

export default function ChartsSection({ trendData, sourceData, selectedSource, onSelectSource, onDateClick, timeRange, onTimeRangeChange, insightHistory, selectedInsightIdx, onSelectInsight }: Props) {
  const [historyMenuOpen, setHistoryMenuOpen] = useState(false)
  const selectedHistoryLabel = useMemo(() => {
    const item = insightHistory?.[selectedInsightIdx]
    if (!item || selectedInsightIdx === 0) return '最新信号'
    return new Date(item.generated_at).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
  }, [insightHistory, selectedInsightIdx])

  return (
    <section className="charts-grid charts-section-spaced">
      <div className="glass chart-card">
        {/* 图表Header：标题 + 时间范围 + 信号时段 */}
        <div className="chart-card-head">
          <h3 className="chart-title">
            <Zap size={18} color="#2dd4bf" /> 信号爆发趋势
          </h3>
          <div className="chart-head-actions">
            {/* 7天/30天切换 - Apple风格pill toggle */}
            <SegmentedControl
              value={timeRange}
              ariaLabel="趋势时间范围"
              onChange={onTimeRangeChange}
              options={[
                { value: '7d', label: '7天' },
                { value: '30d', label: '30天' },
              ]}
            />
            {/* 信号时段选择 - 仅在有多条历史时显示 */}
            {insightHistory && insightHistory.length > 1 && (
              <PopoverMenu
                open={historyMenuOpen}
                onOpenChange={setHistoryMenuOpen}
                align="end"
                trigger={(
                  <button className="history-menu-trigger" aria-expanded={historyMenuOpen}>
                    {selectedHistoryLabel}
                  </button>
                )}
              >
                <MenuPanel className="history-menu-list">
                    {insightHistory.map((item, idx) => (
                      <button
                        key={item.generated_at}
                        className={selectedInsightIdx === idx ? 'active' : ''}
                        onClick={() => {
                          onSelectInsight(idx)
                          setHistoryMenuOpen(false)
                        }}
                      >
                        {idx === 0 ? '最新信号' : new Date(item.generated_at).toLocaleString('zh-CN', {
                          month: '2-digit',
                          day: '2-digit',
                          hour: '2-digit',
                          minute: '2-digit',
                          hour12: false,
                        })}
                      </button>
                    ))}
                </MenuPanel>
              </PopoverMenu>
            )}
          </div>
        </div>
        <div className="chart-body chart-body-spaced">
          <ResponsiveContainer width="100%" height={250} minWidth={0} minHeight={250}>
            <AreaChart
              data={trendData}
              margin={{ top: 10, right: 8, left: -12, bottom: 20 }}
              onClick={(payload: Record<string, unknown>) => {
                if (!onDateClick) return
                const activePayload = payload?.activePayload as Array<{ payload?: TrendPoint }> | undefined
                const point = activePayload?.[0]?.payload
                if (point?.dayKey) onDateClick(point.dayKey)
              }}
              style={{ cursor: onDateClick ? 'pointer' : 'default' }}
            >
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
              <XAxis dataKey="name" tick={{ fill: '#8aa3be', fontSize: 11 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fill: '#8aa3be', fontSize: 11 }} tickLine={false} axisLine={false} width={36} />
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
        <div className="chart-body">
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
                className="source-pie"
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
