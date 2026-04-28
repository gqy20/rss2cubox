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

function getApiSource(): string {
  return process.env.API_SOURCE || 'ic'
}

export async function loadIcArticles(): Promise<EventRow[]> {
  const items = await fetchAllArticles(getBaseUrl(), getSourceType())
  return items.map((data: IcArticle) => normalizeArticle(data))
}

function getApiBaseUrl(): string {
  if (typeof window !== 'undefined') {
    return '' // Browser will use relative URL
  }
  // Server-side: need absolute URL
  return process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:3000'
}

export async function loadLocalArticles(): Promise<EventRow[]> {
  const baseUrl = getApiBaseUrl()
  const allItems: EventRow[] = []
  const pageSize = 100
  let cursor: string | null = null
  let hasMore = true

  while (hasMore) {
    const urlStr = baseUrl
      ? `${baseUrl}/api/signals/local?limit=${pageSize}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`
      : `/api/signals/local?limit=${pageSize}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`
    const response = await fetch(urlStr)
    if (!response.ok) {
      throw new Error(`Local API failed: ${response.status}`)
    }
    const jsonData = await response.json() as { data?: EventRow[], cursor?: string | null, hasMore?: boolean }
    if (jsonData.data && jsonData.data.length > 0) {
      allItems.push(...jsonData.data)
      hasMore = jsonData.hasMore ?? false
      cursor = jsonData.cursor ?? null
    } else {
      hasMore = false
    }
  }

  return allItems
}

export async function loadArticles(): Promise<EventRow[]> {
  const source = getApiSource()
  if (source === 'local') {
    return loadLocalArticles()
  }
  return loadIcArticles()
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
