export type Row = {
  search_field?: string
  search_excerpt?: string
  id: string
  title: string
  url: string
  source: string
  time: string
  exported?: boolean
  enriched?: boolean
  importance_score?: number
  content_source?: string
  signal_type?: number
  evidence_strength?: number
  novelty_score?: number
  impact_horizon?: number
  confidence?: number
  entities?: string[]
  watch_keywords?: string[]
  prediction?: string
  status?: string
  reason?: string
  tags?: string[]
  core_event?: string
  hidden_signal?: string
  actionable?: string
  source_feed?: string
  source_label?: string
  cover_url?: string
  full_text?: string
  full_text_source?: string
}

export type SignalItem = {
  text: string
  source_urls?: string[]
  source_titles?: string[]
}

export type GlobalInsights = {
  generated_at?: string
  source_count?: number
  trends?: SignalItem[] | string[]
  weak_signals?: SignalItem[] | string[]
  daily_advices?: SignalItem[] | string[]
}
