import { NextResponse } from 'next/server'
import { neon } from '@neondatabase/serverless'

export async function GET() {
  const dbUrl = process.env.NEON_DATABASE_URL
  if (!dbUrl) {
    return NextResponse.json({ error: 'NEON_DATABASE_URL not configured' }, { status: 500 })
  }

  try {
    const sql = neon(dbUrl)
    const rows = await sql`
      SELECT generated_at, data
      FROM global_insights
      ORDER BY generated_at DESC
      LIMIT 30
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
