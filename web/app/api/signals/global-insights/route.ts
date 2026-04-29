import { NextResponse } from 'next/server'
import { neon } from '@neondatabase/serverless'
import { Pool } from 'pg'

const localPool = new Pool({
  connectionString: process.env.LOCAL_DB_URL,
})

export async function GET(request: Request) {
  const url = new URL(request.url)
  const rawLimit = parseInt(url.searchParams.get('limit') || '30', 10)
  const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.min(rawLimit, 100) : 30

  const localDbUrl = process.env.LOCAL_DB_URL
  if (localDbUrl) {
    try {
      const client = await localPool.connect()
      try {
        const rows = await client.query(
          `
          SELECT generated_at, data
          FROM global_insights
          ORDER BY generated_at DESC
          LIMIT $1
          `,
          [limit],
        )

        const result = rows.rows.map((row) => ({
          generated_at: row.generated_at,
          data: row.data,
        }))

        return NextResponse.json({ data: result })
      } finally {
        client.release()
      }
    } catch (error) {
      console.error('Failed to fetch local global_insights:', error)
    }
  }

  const neonDbUrl = process.env.NEON_DATABASE_URL
  if (!neonDbUrl) {
    return NextResponse.json({ error: 'LOCAL_DB_URL or NEON_DATABASE_URL not configured' }, { status: 500 })
  }

  try {
    const sql = neon(neonDbUrl)
    const rows = await sql`
      SELECT generated_at, data
      FROM global_insights
      ORDER BY generated_at DESC
      LIMIT ${limit}
    `

    const result = rows.map((row) => ({
      generated_at: row.generated_at,
      data: row.data,
    }))

    return NextResponse.json({ data: result })
  } catch (error) {
    console.error('Failed to fetch global_insights:', error)
    return NextResponse.json({ error: 'Failed to fetch global_insights' }, { status: 500 })
  }
}
