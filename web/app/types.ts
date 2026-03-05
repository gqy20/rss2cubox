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
