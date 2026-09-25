import type { Row, SignalItem } from '../app/types'

export function safeUrl(value: string | null | undefined): string | undefined {
  if (!value) return undefined
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined
  } catch {
    return undefined
  }
}
// Intl formatters are expensive to construct; share module-level instances.
const dayFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})
const timeFormatter = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})
export function dateLabel(value?: string | null, withTime = false): string {
  if (!value) return '未记录'
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '未记录'
  return (withTime ? timeFormatter : dayFormatter).format(date)
}
export function plainText(value?: string | null): string {
  return (value || '')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/[*#`>]/g, '')
    .trim()
}
export function excerpt(value?: string | null, length = 120): string {
  const text = plainText(value)
  return text.length > length ? `${text.slice(0, length)}…` : text
}
export function insightItems(value: unknown): SignalItem[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (typeof item === 'string')
      return item.trim() ? [{ text: item.trim() }] : []
    if (!item || typeof item !== 'object') return []
    const text = String(item.text || item.content || item.title || '').trim()
    if (!text) return []
    return [
      {
        text,
        source_urls: Array.isArray(item.source_urls)
          ? item.source_urls.filter(
              (url: unknown) => typeof url === 'string' && safeUrl(url),
            )
          : [],
        source_titles: Array.isArray(item.source_titles)
          ? item.source_titles.map(String)
          : [],
      },
    ]
  })
}
// A homepage must not become eight consecutive posts from the same feed.
export function diverseArticles(rows: Row[], limit = 8): Row[] {
  const selected: Row[] = [],
    deferred: Row[] = []
  const sources = new Map<string, number>(),
    seen = new Set<string>()
  for (const row of rows) {
    if (seen.has(row.url || row.id)) continue
    seen.add(row.url || row.id)
    const count = sources.get(row.source) || 0
    if (count < 2) {
      selected.push(row)
      sources.set(row.source, count + 1)
    } else deferred.push(row)
  }
  return [...selected, ...deferred].slice(0, limit)
}
export const clusterStatus: Record<string, string> = {
  new: '新发现',
  warming: '持续升温',
  bursting: '集中出现',
  mature: '稳定关注',
  declining: '热度回落',
  invalid: '已排除',
  archived: '已归档',
}
export const predictionStatus: Record<string, string> = {
  pending: '待验证',
  reviewed: '已复盘',
  hit: '命中',
  miss: '未命中',
}
export const healthStatus: Record<string, string> = {
  ok: '采集成功',
  failed: '采集失败',
  timeout: '超时',
  empty: '未发现内容',
  parse_error: '解析失败',
  skipped: '已跳过',
  success: '采集成功',
}
