import { NextResponse } from 'next/server'
import { Pool } from 'pg'

const pool = new Pool({
  connectionString: process.env.LOCAL_DB_URL,
})

export async function GET() {
  const dbUrl = process.env.LOCAL_DB_URL
  if (!dbUrl) {
    return NextResponse.json({ error: 'LOCAL_DB_URL not configured' }, { status: 500 })
  }

  try {
    const client = await pool.connect()
    try {
      // Direct count queries for accurate statistics
      const totalResult = await client.query('SELECT COUNT(*) FROM articles')
      const total = parseInt(totalResult.rows[0]?.count || '0', 10)

      // Count articles with any AI summary (core_event, hidden_signal, actionable, or reason)
      const analyzedResult = await client.query(`
        SELECT COUNT(*) FROM articles
        WHERE (description IS NOT NULL AND description != '')
           OR (hidden_signal IS NOT NULL AND hidden_signal != '')
           OR (actionable IS NOT NULL AND actionable != '')
           OR (reason IS NOT NULL AND reason != '')
      `)
      const analyzed = parseInt(analyzedResult.rows[0]?.count || '0', 10)

      // Count today's articles (using Asia/Shanghai timezone to match frontend)
      const todayResult = await client.query(`
        SELECT COUNT(*) FROM articles
        WHERE publish_time >= (CURRENT_DATE AT TIME ZONE 'Asia/Shanghai')
      `)
      const today = parseInt(todayResult.rows[0]?.count || '0', 10)

      // Count unique sources
      const sourcesResult = await client.query(`
        SELECT COUNT(DISTINCT source_feed_id) FROM articles
        WHERE source_feed_id IS NOT NULL AND source_feed_id != ''
      `)
      const sources = parseInt(sourcesResult.rows[0]?.count || '0', 10)

      // Calculate trend data for last 30 days (using Asia/Shanghai timezone).
      // Keep zero-count days so the 7d/30d chart toggle has a stable timeline.
      const trendResult = await client.query(`
        WITH days AS (
          SELECT generate_series(
            (CURRENT_DATE - INTERVAL '29 days')::date,
            CURRENT_DATE::date,
            INTERVAL '1 day'
          )::date AS day
        ),
        daily AS (
          SELECT
            DATE(publish_time AT TIME ZONE 'Asia/Shanghai') as day,
            COUNT(*) as total,
            SUM(CASE WHEN (description IS NOT NULL AND description != '') OR (hidden_signal IS NOT NULL AND hidden_signal != '') OR (actionable IS NOT NULL AND actionable != '') OR (reason IS NOT NULL AND reason != '') THEN 1 ELSE 0 END) as analyzed
          FROM articles
          WHERE publish_time >= (CURRENT_DATE AT TIME ZONE 'Asia/Shanghai' - INTERVAL '29 days')
          GROUP BY DATE(publish_time AT TIME ZONE 'Asia/Shanghai')
        )
        SELECT
          days.day,
          COALESCE(daily.total, 0) as total,
          COALESCE(daily.analyzed, 0) as analyzed
        FROM days
        LEFT JOIN daily ON daily.day = days.day
        ORDER BY days.day ASC
      `)
      const trendData = trendResult.rows.map((row) => ({
        name: new Date(row.day).toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit' }),
        total: parseInt(row.total, 10),
        analyzed: parseInt(row.analyzed, 10),
      }))

      return NextResponse.json({
        total,
        analyzed,
        today,
        sources,
        trendData,
      })
    } finally {
      client.release()
    }
  } catch (error) {
    console.error('Local DB stats error:', error)
    return NextResponse.json({ error: 'Failed to fetch stats' }, { status: 500 })
  }
}
