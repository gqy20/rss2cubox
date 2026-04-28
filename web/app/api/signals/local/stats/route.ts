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

      // Count today's articles
      const todayResult = await client.query(`
        SELECT COUNT(*) FROM articles
        WHERE publish_time >= CURRENT_DATE
      `)
      const today = parseInt(todayResult.rows[0]?.count || '0', 10)

      // Count unique sources
      const sourcesResult = await client.query(`
        SELECT COUNT(DISTINCT source_feed_id) FROM articles
        WHERE source_feed_id IS NOT NULL AND source_feed_id != ''
      `)
      const sources = parseInt(sourcesResult.rows[0]?.count || '0', 10)

      return NextResponse.json({
        total,
        analyzed,
        today,
        sources,
      })
    } finally {
      client.release()
    }
  } catch (error) {
    console.error('Local DB stats error:', error)
    return NextResponse.json({ error: 'Failed to fetch stats' }, { status: 500 })
  }
}
