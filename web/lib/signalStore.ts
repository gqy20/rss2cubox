import { fetchAllArticles, normalizeArticle, type IcArticle } from './icApi'
import type { Row } from '../app/types'

function getBaseUrl(): string {
  return process.env.IC_API_URL || ''
}

function getSourceType(): string {
  return process.env.IC_SOURCE_TYPE || 'gqy'
}

export async function loadIcArticles(): Promise<Row[]> {
  const items = await fetchAllArticles(getBaseUrl(), getSourceType())
  return items.map((data: IcArticle) => normalizeArticle(data))
}
