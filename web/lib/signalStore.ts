import {
  fetchAllArticles,
  normalizeArticle,
  type EventRow,
  type IcArticle,
} from './icApi'

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
