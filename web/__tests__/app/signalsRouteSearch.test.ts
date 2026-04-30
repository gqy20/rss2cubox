import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'

describe('signals route search coverage', () => {
  it('searches every article table field exposed by local storage', () => {
    const source = readFileSync(
      path.join(process.cwd(), 'app/api/signals/route.ts'),
      'utf8',
    )

    for (const field of [
      'id',
      'source_type',
      'source_article_id',
      'title',
      'source_feed_name',
      'source_feed_id',
      'content_source',
      'hidden_signal',
      'description',
      'reason',
      'actionable',
      'prediction',
      'disconfirming_evidence',
      'cluster_hint',
      'url',
      'pic_url',
      'publish_time::text',
      'created_at::text',
      'updated_at::text',
      'importance_score::text',
      'signal_type::text',
      'evidence_type::text',
      'evidence_strength::text',
      'novelty_score::text',
      'impact_horizon::text',
      'audience::text',
      'market_stage::text',
      'confidence::text',
      'entities::text',
      'watch_keywords::text',
      'enrich_meta::text',
      'tags::text',
    ]) {
      expect(source).toContain(field)
    }

    expect(source).toContain('OR title ILIKE')
    expect(source).not.toContain('source_article_id ILIKE $${paramIndex}\n      title ILIKE')
  })
})
