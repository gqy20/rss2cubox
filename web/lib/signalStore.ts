import { neon } from '@neondatabase/serverless'
import {
  fetchAllArticles,
  normalizeArticle,
  type EventRow,
  type GlobalInsights,
  type IcArticle,
} from './icApi'

function getInsightsSql() {
  const url = process.env.NEON_DATABASE_URL
  if (!url) return null
  return neon(url)
}

function getBaseUrl(): string {
  return process.env.IC_API_URL || ''
}

function getSourceType(): string {
  return process.env.IC_SOURCE_TYPE || 'gqy'
}

export async function loadIcArticles(): Promise<EventRow[]> {
  const items = await fetchAllArticles(getBaseUrl(), getSourceType())
  return items.map((data: IcArticle) => normalizeArticle(data))
}

export async function loadGlobalInsights(): Promise<GlobalInsights | null> {
  const sql = getInsightsSql()
  if (!sql) return null
  const rows = await sql`
    SELECT data
    FROM global_insights
    ORDER BY generated_at DESC
    LIMIT 1
  `
  return (rows[0]?.data as GlobalInsights) ?? null
}
