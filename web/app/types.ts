export type Row = {
  id: string
  title: string
  url: string
  source: string
  time: string
  score?: number
  pushed?: boolean
  enriched?: boolean
  reason?: string
  tags?: string[]
  core_event?: string
  hidden_signal?: string
  actionable?: string
  source_feed?: string
  source_label?: string
  cover_url?: string
}

export type Metrics = {
  generated_at?: string
  updates_total?: number
  sources_total?: number
  top_sources?: Array<{ source: string; count: number }>
  // KPI 数据（服务端计算）
  total_all?: number
  high_all?: number
  total_today?: number
  total_yesterday?: number
  high_today?: number
  high_yesterday?: number
  sources_today?: number
  sources_yesterday?: number
  // 趋势数据
  trend_data?: Array<{ name: string; total: number; high: number }>
  // 每日数据量（用于右侧分组显示总数）
  daily_counts?: Record<string, number>
}

export type GlobalInsights = {
  generated_at?: string
  source_count?: number
  trends?: string[]
  weak_signals?: string[]
  daily_advices?: string[]
}

export type InsightKey = 'trends' | 'weak_signals' | 'daily_advices'
export type ExportScope = 'current' | 'high' | 'today'
export type PendingExport = { label: string; rows: Row[] } | null
