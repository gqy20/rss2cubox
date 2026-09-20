import type { Row, GlobalInsights } from '../app/types'

export type Policy = {
  search_field?: string
  search_excerpt?: string
  id: string
  title: string
  url: string
  site_name: string | null
  region: string | null
  stage: string | null
  instrument_type: string | null
  policy_lineage: string | null
  jurisdiction: string | null
  issuing_authority: string | null
  document_number: string | null
  obligation_level: string | null
  published_at: string | null
  effective_date: string | null
  comment_deadline: string | null
  summary: string | null
  source_quote: string | null
  key_provisions: unknown[]
  affected_parties: string[]
  ai_relevance: number | null
  ai_relevance_reason: string | null
  confidence: number | null
  enriched_at: string | null
  full_text?: string | null
}
export type Cluster = {
  id: number
  label: string
  summary: string | null
  status: string
  article_count: number
  source_count: number
  entities: string[]
  watch_keywords: string[]
  updated_at: string
}
export type Prediction = {
  id: number
  signal_cluster_id: number | null
  prediction_title: string
  prediction_body: string
  status: string
  confidence: number | null
  target_start_at: string
  target_end_at: string
  created_at: string
  expected_evidence: Record<string, unknown>
  disconfirming_evidence: string | null
  cluster_label: string | null
}
export type Review = {
  id: number
  prediction_id: number
  prediction_title: string
  score: number
  hit_level: string
  reviewed_at: string
  actual_observation: string | null
  why_score: string | null
  improvement_advice: string | null
  supporting_articles: string[]
  contradicting_articles: string[]
}
export type SourceHealth = {
  name: string
  kind: '科技' | '政策'
  status: string
  last_run: string | null
  last_success?: string | null
  fetched: number
  duration_ms: number
  empty_runs?: number
}
export type ArticleStats = {
  total: number
  high: number
  analyzed: number
  sources: number
  latest: string | null
}
export type PolicyStats = { total: number; analyzed: number }
export type JournalData = {
  articles: Row[]
  stats: ArticleStats | null
  policyStats: PolicyStats | null
  policies: Policy[]
  clusters: Cluster[]
  predictions: Prediction[]
  reviews: Review[]
  insights: GlobalInsights | null
  issues: string[]
  loadedAt: string
}
export type PageResult<T> = {
  nextCursor?: string | null
  snapshot?: string
  data: T[]
  total: number
  page: number
  hasMore: boolean
}
