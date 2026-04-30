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
  return process.env.API_SOURCE || 'local'
}

export async function loadIcArticles(): Promise<EventRow[]> {
  const items = await fetchAllArticles(getBaseUrl(), getSourceType())
  return items.map((data: IcArticle) => normalizeArticle(data))
}

function getApiBaseUrl(apiBaseUrl?: string): string {
  if (typeof window !== 'undefined') {
    return '' // Browser will use relative URL
  }
  // Server-side: need absolute URL
  return apiBaseUrl || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:3424'
}

export async function loadLocalArticles(apiBaseUrl?: string): Promise<EventRow[]> {
  const baseUrl = getApiBaseUrl(apiBaseUrl)
  const pageSize = 50
  const urlStr = baseUrl
    ? `${baseUrl}/api/signals/local?limit=${pageSize}`
    : `/api/signals/local?limit=${pageSize}`
  const response = await fetch(urlStr, { cache: 'no-store' })
  if (!response.ok) {
    throw new Error(`Local API failed: ${response.status}`)
  }
  const jsonData = await response.json() as { data?: EventRow[] }
  return Array.isArray(jsonData.data) ? jsonData.data : []
}

export async function loadArticles(apiBaseUrl?: string): Promise<EventRow[]> {
  const source = getApiSource()
  if (source === 'local') {
    return loadLocalArticles(apiBaseUrl)
  }
  return loadIcArticles()
}

export type LocalStats = {
  total: number
  analyzed: number
  today: number
  yesterday?: number
  analyzedToday?: number
  analyzedYesterday?: number
  sourcesToday?: number
  sourcesYesterday?: number
  sources: number
  topSourceCounts?: Array<{ source: string; count: number }>
  trendData?: Array<{ name: string; total: number; analyzed: number }>
  dailyTotals?: Record<string, number>
}

export async function loadLocalStats(apiBaseUrl?: string): Promise<LocalStats | null> {
  const baseUrl = getApiBaseUrl(apiBaseUrl)
  const url = baseUrl
    ? `${baseUrl}/api/signals/local/stats`
    : '/api/signals/local/stats'
  try {
    const response = await fetch(url, { cache: 'no-store' })
    if (!response.ok) return null
    return await response.json() as LocalStats
  } catch {
    return null
  }
}

export async function loadGlobalInsights(apiBaseUrl?: string): Promise<GlobalInsights | null> {
  const baseUrl = getApiBaseUrl(apiBaseUrl)
  const url = baseUrl
    ? `${baseUrl}/api/signals/global-insights?limit=1`
    : '/api/signals/global-insights?limit=1'

  try {
    const response = await fetch(url, { cache: 'no-store' })
    if (response.ok) {
      const jsonData = await response.json() as { data?: InsightHistoryItem[] }
      const latest = jsonData.data?.[0]?.data
      if (latest) return latest
    }
  } catch {
    // Fall back to the direct Neon reader below for older deployments.
  }

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

export type InsightHistoryItem = {
  generated_at: string
  data: GlobalInsights
}

export async function loadAllGlobalInsights(limit: number = 30): Promise<InsightHistoryItem[]> {
  // 通过 API 路由获取，避免在客户端直接暴露数据库连接
  const baseUrl = typeof window !== 'undefined' ? '' : (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:3424')
  const url = baseUrl ? `${baseUrl}/api/signals/global-insights` : '/api/signals/global-insights'

  try {
    const response = await fetch(url, { cache: 'no-store' })
    if (!response.ok) {
      console.error('Failed to fetch global insights:', response.status)
      return []
    }
    const jsonData = await response.json() as { data?: InsightHistoryItem[] }
    return jsonData.data ?? []
  } catch (error) {
    console.error('Failed to fetch global insights:', error)
    return []
  }
}
