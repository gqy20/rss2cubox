/** Local, bounded return paths are navigation state, never arbitrary redirect targets. */
const BASE = 'https://reader.invalid'
export function safeReturnPath(value?: string | null): string | null {
  if (
    typeof value !== 'string' ||
    !value ||
    value.length > 2000 ||
    !value.startsWith('/') ||
    value.startsWith('//') ||
    /[\\\u0000-\u001f]/.test(value)
  )
    return null
  try {
    const url = new URL(value, BASE)
    if (
      url.origin !== BASE ||
      !/^\/(?:signals|policies(?:\/[^/]+)?|topics|monitor|saved|predictions|briefing)?$/.test(
        url.pathname,
      )
    )
      return null
    return url.pathname + url.search + url.hash
  } catch {
    return null
  }
}
export function withOrigin(destination: string, origin?: string | null) {
  const url = new URL(destination, BASE),
    from = safeReturnPath(origin)
  if (from) url.searchParams.set('from', from)
  return url.pathname + url.search + url.hash
}
export function returnLabel(path: string) {
  const route = new URL(path, BASE).pathname
  if (route === '/') return '返回总览'
  if (route === '/topics') return '返回专题'
  if (route === '/monitor') return '返回信源'
  if (route === '/saved') return '返回收藏'
  if (route === '/predictions') return '返回预测'
  if (route === '/briefing') return '返回简报'
  if (route.startsWith('/policies/')) return '返回政策解读'
  return route === '/policies' ? '返回政策列表' : '返回文章列表'
}
export type ReadingContext = {
  from: string
  filters?: {
    topic?: string
    sourceRef?: string
    saved?: string
    mode?: string
  }
}
export function articleDestination(id: string, context?: ReadingContext) {
  const params = new URLSearchParams({ ...context?.filters, id })
  return withOrigin(`/signals?${params}`, context?.from)
}
export function policyDestination(id: string, context?: ReadingContext) {
  return withOrigin(`/policies/${encodeURIComponent(id)}`, context?.from)
}
export function dayInShanghai(value: string) {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return null
  return date.toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' })
}
export function insightFreshness(
  generatedAt: string | null | undefined,
  asOf: string,
) {
  if (!generatedAt || !dayInShanghai(generatedAt)) return '尚未生成'
  return dayInShanghai(generatedAt) === dayInShanghai(asOf)
    ? '今日生成'
    : '历史洞察'
}
