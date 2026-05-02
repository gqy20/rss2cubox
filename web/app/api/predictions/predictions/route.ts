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
          tp.id, tp.prediction_type, tp.created_at, tp.target_start_at, tp.target_end_at,
          tp.horizon_days, tp.prediction_title, tp.prediction_body, tp.watch_keywords,
          tp.expected_evidence, tp.disconfirming_evidence, tp.baseline_metrics,
          tp.confidence, tp.status,
          sc.label AS cluster_label, sc.normalized_label AS cluster_key
        FROM trend_predictions tp
        LEFT JOIN signal_clusters sc ON sc.id = tp.signal_cluster_id
        ORDER BY tp.created_at DESC
      `)
      return NextResponse.json({ data: result.rows }, { headers: NO_STORE_HEADERS })
    } finally {
      client.release()
    }
  } catch (error) {
    console.error('Predictions API error:', error)
    return NextResponse.json({ error: 'Failed to fetch predictions' }, { status: 500, headers: NO_STORE_HEADERS })
  }
}
