import { normalizeSource } from './icApi'

export function buildArticleSearchWhere(search: string, paramIndex: number): { sql: string; value: string } | null {
  if (!search) return null
  return {
    sql: `(
      id ILIKE $${paramIndex}
      OR source_type ILIKE $${paramIndex}
      OR source_article_id ILIKE $${paramIndex}
      OR title ILIKE $${paramIndex}
      OR source_feed_name ILIKE $${paramIndex}
      OR source_feed_id ILIKE $${paramIndex}
      OR content_source ILIKE $${paramIndex}
      OR hidden_signal ILIKE $${paramIndex}
      OR description ILIKE $${paramIndex}
      OR reason ILIKE $${paramIndex}
      OR actionable ILIKE $${paramIndex}
      OR prediction ILIKE $${paramIndex}
      OR disconfirming_evidence ILIKE $${paramIndex}
      OR cluster_hint ILIKE $${paramIndex}
      OR url ILIKE $${paramIndex}
      OR pic_url ILIKE $${paramIndex}
      OR publish_time::text ILIKE $${paramIndex}
      OR created_at::text ILIKE $${paramIndex}
      OR updated_at::text ILIKE $${paramIndex}
      OR importance_score::text ILIKE $${paramIndex}
      OR signal_type::text ILIKE $${paramIndex}
      OR evidence_type::text ILIKE $${paramIndex}
      OR evidence_strength::text ILIKE $${paramIndex}
      OR novelty_score::text ILIKE $${paramIndex}
      OR impact_horizon::text ILIKE $${paramIndex}
      OR audience::text ILIKE $${paramIndex}
      OR market_stage::text ILIKE $${paramIndex}
      OR confidence::text ILIKE $${paramIndex}
      OR entities::text ILIKE $${paramIndex}
      OR watch_keywords::text ILIKE $${paramIndex}
      OR enrich_meta::text ILIKE $${paramIndex}
      OR tags::text ILIKE $${paramIndex}
    )`,
    value: `%${search}%`,
  }
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item)).filter((item) => item.trim().length > 0)
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  return undefined
}

export function formatLocalArticleRow(row: any) {
  return {
    id: row.id,
    title: row.title || '',
    url: row.url || '',
    source: normalizeSource({ source_feed_name: row.source_feed_name, source_feed_id: row.source_feed_id, url: row.url } as any),
    time: row.display_time || '',
    exported: true,
    status: 'exported',
    tags: Array.isArray(row.tags) ? row.tags : [],
    core_event: row.description || '',
    hidden_signal: row.hidden_signal || '',
    importance_score: asNumber(row.importance_score),
    content_source: row.content_source || '',
    signal_type: asNumber(row.signal_type),
    evidence_strength: asNumber(row.evidence_strength),
    novelty_score: asNumber(row.novelty_score),
    impact_horizon: asNumber(row.impact_horizon),
    confidence: asNumber(row.confidence),
    entities: asStringArray(row.entities),
    watch_keywords: asStringArray(row.watch_keywords),
    prediction: row.prediction || '',
    actionable: row.actionable || '',
    reason: row.reason || '',
    cover_url: row.pic_url || '',
    source_feed: row.source_feed_id || '',
    source_label: row.source_feed_name || '',
    full_text: row.full_text || undefined,
    full_text_source: row.full_text_source || undefined,
  }
}
