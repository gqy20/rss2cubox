import { normalizeSource } from './icApi'
import type { Row } from '../app/types'

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item)).filter((item) => item.trim().length > 0)
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  return undefined
}

export function formatLocalArticleRow(row: any): Row {
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
