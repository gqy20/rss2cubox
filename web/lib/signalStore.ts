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
  const allItems: any[] = []
  const pageSize = 100
  let page = 1
  let hasMore = true

  while (hasMore) {
    const url = baseUrl
      ? `${baseUrl}/api/signals/local?page=${page}&limit=${pageSize}`
      : `/api/signals/local?page=${page}&limit=${pageSize}`
    const response = await fetch(url)
    if (!response.ok) {
      throw new Error(`Local API failed: ${response.status}`)
    }
    const data = await response.json()
    if (data.data && data.data.length > 0) {
      allItems.push(...data.data)
      hasMore = data.hasMore
      page++
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
