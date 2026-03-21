export type Row = {
  id: string
  title: string
  url: string
  source: string
  time: string
  exported?: boolean
  enriched?: boolean
  status?: string
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
  signals_total?: number
  exported_total?: number
  active_sources_total?: number
  top_source_counts?: Array<{ source: string; count: number }>
  // KPI 数据（服务端计算）
  total_all?: number
  analyzed_total?: number
  total_today?: number
  total_yesterday?: number
  analyzed_today?: number
  analyzed_yesterday?: number
  sources_today?: number
  sources_yesterday?: number
  // 趋势数据
  timeline_points?: Array<{ name: string; total: number; analyzed: number }>
  // 每日数据量（用于右侧分组显示总数）
  daily_totals?: Record<string, number>
}

export type GlobalInsights = {
  generated_at?: string
  source_count?: number
  trends?: string[]
  weak_signals?: string[]
  daily_advices?: string[]
}

export type InsightKey = 'trends' | 'weak_signals' | 'daily_advices'
