import { NextResponse } from 'next/server'
import { Pool } from 'pg'

export const dynamic = 'force-dynamic'
export const revalidate = 0

const pool = new Pool({ connectionString: process.env.LOCAL_DB_URL })

const NO_STORE_HEADERS = {
  'Cache-Control': 'no-store, no-cache, must-revalidate, proxy-revalidate',
  Pragma: 'no-cache',
  Expires: '0',
}

export async function GET() {
  const dbUrl = process.env.LOCAL_DB_URL
  if (!dbUrl) {
    return NextResponse.json({ error: 'LOCAL_DB_URL not configured' }, { status: 500, headers: NO_STORE_HEADERS })
  }

  try {
    const client = await pool.connect()
    try {
      const result = await client.query(`
        SELECT
          sc.id, sc.label, sc.normalized_label, sc.signal_type, sc.status,
          sc.summary, sc.entities, sc.watch_keywords,
          sc.first_seen_at, sc.last_seen_at, sc.article_count, sc.source_count,
          sc.avg_importance, sc.avg_evidence_strength, sc.avg_novelty, sc.avg_confidence,
          sc.prediction_score_avg, sc.created_at, sc.updated_at,
          COALESCE(
            json_agg(json_build_object('article_id', sca.article_id, 'relevance_score', sca.relevance_score))
            FILTER (WHERE sca.article_id IS NOT NULL), '[]'
          ) AS linked_articles
        FROM signal_clusters sc
        LEFT JOIN signal_cluster_articles sca ON sca.cluster_id = sc.id
        GROUP BY sc.id
        ORDER BY sc.updated_at DESC
      `)
      return NextResponse.json({ data: result.rows }, { headers: NO_STORE_HEADERS })
    } finally {
      client.release()
    }
  } catch (error) {
    console.error('Predictions clusters API error:', error)
    return NextResponse.json({ error: 'Failed to fetch signal clusters' }, { status: 500, headers: NO_STORE_HEADERS })
  }
}
