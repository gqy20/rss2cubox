import { NextResponse } from 'next/server'
import { Pool } from 'pg'

export const dynamic = 'force-dynamic'
export const revalidate = 0

const pool = new Pool({
  connectionString: process.env.LOCAL_DB_URL,
})

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

      // Use Beijing timezone for all date comparisons.
      // Data is stored in UTC; convert to Asia/Shanghai before extracting date.
      const TZ_CAST = "(COALESCE(publish_time, created_at) AT TIME ZONE 'Asia/Shanghai')"
      const todayResult = await client.query(`
        SELECT
          COUNT(*) FILTER (WHERE ${TZ_CAST}::date = CURRENT_DATE) as today,
          COUNT(*) FILTER (WHERE ${TZ_CAST}::date = CURRENT_DATE - INTERVAL '1 day') as yesterday,
          COUNT(*) FILTER (
            WHERE ${TZ_CAST}::date = CURRENT_DATE
              AND ((description IS NOT NULL AND description != '') OR (hidden_signal IS NOT NULL AND hidden_signal != '') OR (actionable IS NOT NULL AND actionable != '') OR (reason IS NOT NULL AND reason != ''))
          ) as analyzed_today,
          COUNT(*) FILTER (
            WHERE ${TZ_CAST}::date = CURRENT_DATE - INTERVAL '1 day'
              AND ((description IS NOT NULL AND description != '') OR (hidden_signal IS NOT NULL AND hidden_signal != '') OR (actionable IS NOT NULL AND actionable != '') OR (reason IS NOT NULL AND reason != ''))
          ) as analyzed_yesterday,
          COUNT(DISTINCT source_feed_id) FILTER (WHERE ${TZ_CAST}::date = CURRENT_DATE AND source_feed_id IS NOT NULL AND source_feed_id != '') as sources_today,
          COUNT(DISTINCT source_feed_id) FILTER (WHERE ${TZ_CAST}::date = CURRENT_DATE - INTERVAL '1 day' AND source_feed_id IS NOT NULL AND source_feed_id != '') as sources_yesterday
        FROM articles
      `)
      const today = parseInt(todayResult.rows[0]?.today || '0', 10)
      const yesterday = parseInt(todayResult.rows[0]?.yesterday || '0', 10)
      const analyzedToday = parseInt(todayResult.rows[0]?.analyzed_today || '0', 10)
      const analyzedYesterday = parseInt(todayResult.rows[0]?.analyzed_yesterday || '0', 10)
      const sourcesToday = parseInt(todayResult.rows[0]?.sources_today || '0', 10)
      const sourcesYesterday = parseInt(todayResult.rows[0]?.sources_yesterday || '0', 10)

      // Count unique sources
      const sourcesResult = await client.query(`
        SELECT COUNT(DISTINCT source_feed_id) FROM articles
        WHERE source_feed_id IS NOT NULL AND source_feed_id != ''
      `)
      const sources = parseInt(sourcesResult.rows[0]?.count || '0', 10)

      const topSourcesResult = await client.query(`
        SELECT COALESCE(NULLIF(source_feed_name, ''), NULLIF(source_feed_id, ''), 'unknown') as source,
               COUNT(*) as count
        FROM articles
        GROUP BY COALESCE(NULLIF(source_feed_name, ''), NULLIF(source_feed_id, ''), 'unknown')
        ORDER BY COUNT(*) DESC
        LIMIT 10
      `)
      const topSourceCounts = topSourcesResult.rows.map((row) => ({
        source: String(row.source || 'unknown'),
        count: parseInt(row.count, 10),
      }))

      // Calculate display-time trend data for last 30 days.
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
            ${TZ_CAST}::date as day,
            COUNT(*) as total,
            SUM(CASE WHEN (description IS NOT NULL AND description != '') OR (hidden_signal IS NOT NULL AND hidden_signal != '') OR (actionable IS NOT NULL AND actionable != '') OR (reason IS NOT NULL AND reason != '') THEN 1 ELSE 0 END) as analyzed
          FROM articles
          WHERE COALESCE(publish_time, created_at) >= NOW() - INTERVAL '29 days'
          GROUP BY ${TZ_CAST}::date
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

      const dailyTotalsResult = await client.query(`
        SELECT to_char(${TZ_CAST}::date, 'YYYY-MM-DD') as day, COUNT(*) as total
        FROM articles
        GROUP BY ${TZ_CAST}::date
        ORDER BY day DESC
      `)
      const dailyTotals = Object.fromEntries(
        dailyTotalsResult.rows.map((row) => [
          String(row.day),
          parseInt(row.total, 10),
        ]),
      )

      return NextResponse.json({
        total,
        analyzed,
        today,
        yesterday,
        analyzedToday,
        analyzedYesterday,
        sourcesToday,
        sourcesYesterday,
        sources,
        topSourceCounts,
        trendData,
        dailyTotals,
      }, { headers: NO_STORE_HEADERS })
    } finally {
      client.release()
    }
  } catch (error) {
    console.error('Local DB stats error:', error)
    return NextResponse.json({ error: 'Failed to fetch stats' }, { status: 500, headers: NO_STORE_HEADERS })
  }
}
