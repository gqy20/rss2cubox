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
          pr.id, pr.prediction_id, pr.reviewed_at, pr.score, pr.hit_level,
          pr.supporting_articles, pr.contradicting_articles,
          pr.actual_observation, pr.why_score, pr.improvement_advice, pr.review_metrics,
          tp.prediction_title, tp.prediction_body, tp.status AS prediction_status,
          sc.label AS cluster_label
        FROM prediction_reviews pr
        JOIN trend_predictions tp ON tp.id = pr.prediction_id
        LEFT JOIN signal_clusters sc ON sc.id = tp.signal_cluster_id
        ORDER BY pr.reviewed_at DESC
      `)
      return NextResponse.json({ data: result.rows }, { headers: NO_STORE_HEADERS })
    } finally {
      client.release()
    }
  } catch (error) {
    console.error('Prediction reviews API error:', error)
    return NextResponse.json({ error: 'Failed to fetch prediction reviews' }, { status: 500, headers: NO_STORE_HEADERS })
  }
}
