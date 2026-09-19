/** Shared URL rules keep the top search, filters and browser history in sync. */
export type SearchScope = 'signals' | 'policies'
export const filterKeys = [
  'mode',
  'date',
  'source',
  'tag',
  'region',
  'stage',
  'instrument_type',
  'topic',
  'sourceRef',
  'saved',
] as const
export function scopeForPath(pathname: string): SearchScope {
  return pathname.startsWith('/policies') ? 'policies' : 'signals'
}
export function readerUrl(
  scope: SearchScope,
  current: URLSearchParams,
  changes: Record<string, string | null>,
  resetPage = true,
) {
  const next = new URLSearchParams(current)
  if (resetPage) {
    next.delete('page')
    next.delete('id')
    next.delete('tab')
  }
  for (const [key, value] of Object.entries(changes)) {
    const normalized =
      key === 'search' ? (value || '').trim().slice(0, 300) : value
    if (
      !normalized ||
      (key === 'mode' && normalized === 'all') ||
      (key === 'page' && normalized === '1')
    )
      next.delete(key)
    else next.set(key, normalized)
  }
  const query = next.toString()
  return `/${scope}${query ? `?${query}` : ''}`
}
export function activeFilterCount(params: URLSearchParams) {
  return filterKeys.filter(
    (key) => Boolean(params.get(key)) && params.get(key) !== 'all',
  ).length
}

/** Fixed content columns only: identifiers, URL tokens and scoring metadata are not searchable text. */
export function buildContentSearch(search: string, kind: SearchScope) {
  if (!search) return null
  const columns: [string, string][] =
    kind === 'signals'
      ? [
          ['title', '标题'],
          ['source_feed_name', '来源'],
          ['description', '摘要'],
          ['hidden_signal', '隐藏信号'],
          ['reason', '判断依据'],
          ['actionable', '行动建议'],
          ['prediction', '预测'],
          ['tags::text', '标签'],
          ['entities::text', '实体'],
          ['full_text', '正文'],
        ]
      : [
          ['title', '标题'],
          ['issuing_authority', '发布机构'],
          ['summary', '摘要'],
          ['affected_parties::text', '适用主体'],
          ['key_provisions::text', '关键条款'],
          ['source_quote', '原文引句'],
          ['full_text', '正文'],
        ]
  const cases = columns
    .map(([column]) => `WHEN ${column} ILIKE $1 THEN ${column}`)
    .join(' ')
  const labels = columns
    .map(([column, label]) => `WHEN ${column} ILIKE $1 THEN '${label}'`)
    .join(' ')
  const match = `(CASE ${cases} ELSE '' END)`
  return {
    where: `(${columns.map(([column]) => `${column} ILIKE $1`).join(' OR ')}) AND $2::text IS NOT NULL`,
    values: [`%${search.replace(/[\\%_]/g, '\\$&')}%`, search.toLowerCase()],
    select: `, (CASE ${labels} ELSE NULL END) AS search_field,
      (CASE WHEN strpos(lower(${match}), $2) > 51 THEN '…' ELSE '' END || substring(${match} FROM greatest(strpos(lower(${match}), $2) - 50, 1) FOR 240)) AS search_excerpt`,
    order: `CASE WHEN title ILIKE $1 THEN 0 ELSE 1 END,`,
  }
}
