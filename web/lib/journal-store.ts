import { Pool, type QueryResultRow } from 'pg'
import { createHash } from 'node:crypto'
import { cache } from 'react'
import { formatLocalArticleRow } from './localArticleRows'
import { buildContentSearch, type SearchScope } from './reader-search'
import {
  cursorQuery,
  decodeCursor,
  encodeCursor,
  cursorBoundary,
  savedFingerprint,
} from './reader-cursor'
import { diverseArticles } from './journal-utils'
import { loadIcArticles } from './signalStore'
import type { Row, GlobalInsights } from '../app/types'
import type {
  ArticleStats,
  PolicyStats,
  Policy,
  Cluster,
  Prediction,
  Review,
  JournalData,
  PageResult,
  SourceHealth,
} from './journal-types'

// This module is only imported by server pages and route handlers. Never expose connection strings.
const globalDb = globalThis as typeof globalThis & { journalPool?: Pool }
function pool() {
  if (!process.env.LOCAL_DB_URL) throw new Error('Local database unavailable')
  if (!globalDb.journalPool)
    globalDb.journalPool = new Pool({
      connectionString: process.env.LOCAL_DB_URL,
      max: 5,
      connectionTimeoutMillis: 4000,
      statement_timeout: 12000,
      idleTimeoutMillis: 10000,
    })
  return globalDb.journalPool
}
async function query<T extends QueryResultRow>(
  sql: string,
  params: unknown[] = [],
): Promise<T[]> {
  const result = await pool().query<T>(sql, params)
  return JSON.parse(JSON.stringify(result.rows)) as T[]
}
const articleFields = `id, title, url, source_feed_name, source_feed_id, pic_url, description,
  tags, importance_score, reason, actionable, hidden_signal, content_source, signal_type,
  evidence_strength, novelty_score, impact_horizon, confidence, entities, watch_keywords, prediction,
  COALESCE(publish_time, created_at) AS display_time`
const policyFields = `id, title, url, site_name, region, stage, instrument_type, jurisdiction,
  issuing_authority, document_number, obligation_level, published_at, effective_date::text,
  comment_deadline::text, summary, source_quote, key_provisions, affected_parties, ai_relevance,
  ai_relevance_reason, confidence, enriched_at`

function pageNumber(params: URLSearchParams) {
  const value = Number(params.get('page'))
  return Number.isFinite(value)
    ? Math.max(1, Math.min(100000, Math.floor(value)))
    : 1
}

export async function articleStats(): Promise<ArticleStats> {
  const [row] = await query<ArticleStats>(`SELECT count(*)::int AS total,
    count(*) FILTER (WHERE importance_score >= 4)::int AS high,
    count(*) FILTER (WHERE COALESCE(hidden_signal,'') <> '' OR COALESCE(reason,'') <> '' OR COALESCE(actionable,'') <> '')::int AS analyzed,
    count(DISTINCT NULLIF(source_feed_id,''))::int AS sources, max(created_at) AS latest FROM articles`)
  return row
}
export async function policyStats(): Promise<PolicyStats> {
  const [row] = await query<PolicyStats>(
    'SELECT count(*)::int AS total, count(*) FILTER (WHERE enriched_at IS NOT NULL)::int AS analyzed FROM policy_documents',
  )
  return row
}
export async function readSignals(
  params: URLSearchParams,
  selectedIds?: string[],
): Promise<PageResult<Row>> {
  if (params.get('saved') === '1' && selectedIds === undefined)
    throw new Error('Missing saved selection')
  if (selectedIds !== undefined) {
    params = new URLSearchParams(params)
    params.set('selection', savedFingerprint(selectedIds))
  }
  const sourceRef = params.get('sourceRef') || ''
  if (sourceRef && !/^tech:[a-f0-9]{32}$/.test(sourceRef))
    throw new Error('Invalid source')
  const page = pageNumber(params)
  const search = (params.get('search') || '').trim().slice(0, 300)
  const source = params.get('source') || '',
    tag = params.get('tag') || '',
    date = params.get('date') || ''
  const mode = params.get('mode') || 'all'
  const topic = params.get('topic')?.trim() || ''
  if (topic && (!/^[1-9]\d*$/.test(topic) || Number(topic) > 2147483647))
    throw new Error('Invalid topic')

  if (
    date &&
    (!/^\d{4}-\d{2}-\d{2}$/.test(date) ||
      !Number.isFinite(Date.parse(date)) ||
      new Date(date).toISOString().slice(0, 10) !== date)
  )
    throw new Error('Invalid date')
  if (process.env.API_SOURCE && process.env.API_SOURCE !== 'local') {
    let rows = (await loadIcArticles()) as Row[]
    const topicIds = topic
      ? new Set(
          (
            await query<{ article_id: string }>(
              'SELECT article_id FROM signal_cluster_articles WHERE cluster_id=$1',
              [Number(topic)],
            )
          ).map((r) => r.article_id),
        )
      : null
    rows = rows.filter(
      (r) =>
        (!selectedIds || selectedIds.includes(r.id)) &&
        (!sourceRef ||
          sourceRef ===
            `tech:${createHash('md5')
              .update(r.source_feed || '')
              .digest('hex')}`) &&
        (!topicIds || topicIds.has(r.id)) &&
        (!search || Boolean(articleMatch(r, search))) &&
        (!source || r.source === source) &&
        (!tag || r.tags?.includes(tag)) &&
        (!date ||
          new Date(r.time).toLocaleDateString('en-CA', {
            timeZone: 'Asia/Shanghai',
          }) === date) &&
        (mode !== 'high' || (r.importance_score || 0) >= 4) &&
        (mode !== 'analyzed' ||
          Boolean(r.hidden_signal || r.actionable || r.reason)),
    )
    rows = rows.map((row) => ({
      ...row,
      ...(search ? articleMatch(row, search) : {}),
    }))
    rows.sort(
      (a, b) =>
        Number(
          Boolean(search) &&
            !a.title.toLowerCase().includes(search.toLowerCase()),
        ) -
          Number(
            Boolean(search) &&
              !b.title.toLowerCase().includes(search.toLowerCase()),
          ) || new Date(b.time).getTime() - new Date(a.time).getTime(),
    )
    const signature = cursorQuery('signals', params),
      cursor = decodeCursor(params.get('cursor'), signature),
      snapshot = cursor?.snapshot || new Date().toISOString()
    const rank = (row: Row) =>
      Number(
        Boolean(search) &&
          !row.title.toLowerCase().includes(search.toLowerCase()),
      )
    const time = (row: Row) =>
      Number.isFinite(Date.parse(row.time))
        ? new Date(row.time).toISOString()
        : '0001-01-01T00:00:00.000Z'
    rows = rows.filter((row) => time(row) <= snapshot)
    rows.sort(
      (a, b) =>
        rank(a) - rank(b) ||
        time(b).localeCompare(time(a)) ||
        (a.id < b.id ? 1 : a.id > b.id ? -1 : 0),
    )
    const total = rows.length
    if (cursor)
      rows = rows.filter(
        (row) =>
          rank(row) > cursor.rank ||
          (rank(row) === cursor.rank &&
            (time(row) < cursor.time ||
              (time(row) === cursor.time && row.id < cursor.id))),
      )
    const offset = cursor ? 0 : (page - 1) * 30,
      data = rows.slice(offset, offset + 30),
      last = data.at(-1),
      hasMore = rows.length > offset + 30
    return {
      data,
      total,
      page,
      hasMore,
      snapshot,
      nextCursor:
        hasMore && last
          ? encodeCursor({
              v: 1,
              query: signature,
              snapshot,
              rank: rank(last),
              time: time(last),
              id: last.id,
            })
          : null,
    }
  }

  const values: unknown[] = [],
    where: string[] = []
  const add = (clause: string, value: unknown) => {
    values.push(value)
    where.push(clause.replace('?', `$${values.length}`))
  }
  const searchWhere = buildContentSearch(search, 'signals')
  if (searchWhere) {
    values.push(...searchWhere.values)
    where.push(searchWhere.where)
  }
  if (topic)
    add(
      'EXISTS (SELECT 1 FROM signal_cluster_articles sca WHERE sca.article_id=articles.id AND sca.cluster_id=?::int)',
      Number(topic),
    )
  if (sourceRef) add('md5(source_feed_id) = ?', sourceRef.slice(5))
  if (selectedIds !== undefined) add('id = ANY(?::text[])', selectedIds)
  if (source) add('source_feed_name = ?', source)
  if (tag) add('tags @> ?::jsonb', JSON.stringify([tag]))
  if (date)
    add(
      "(COALESCE(publish_time,created_at) AT TIME ZONE 'Asia/Shanghai')::date = ?::date",
      date,
    )
  if (mode === 'high') where.push('importance_score >= 4')
  if (mode === 'analyzed')
    where.push(
      "(COALESCE(hidden_signal,'') <> '' OR COALESCE(actionable,'') <> '' OR COALESCE(reason,'') <> '')",
    )
  const result = await readCursorPage('signals', params, {
    table: 'articles',
    fields: articleFields + (searchWhere?.select || ''),
    where,
    values,
    time: "COALESCE(publish_time,created_at,'0001-01-01'::timestamptz)",
    created: 'created_at',
    rank: searchWhere ? 'CASE WHEN title ILIKE $1 THEN 0 ELSE 1 END' : '0::int',
  })
  return {
    ...result,
    data: result.data.map((row) => ({
      ...formatLocalArticleRow(row),
      search_field: row.search_field,
      search_excerpt: row.search_excerpt,
    })),
  }
}

export async function readArticle(id: string): Promise<Row | null> {
  if (process.env.API_SOURCE && process.env.API_SOURCE !== 'local')
    return (await loadIcArticles()).find((row) => row.id === id) || null
  const [row] = await query(
    `SELECT ${articleFields}, full_text, full_text_source FROM articles WHERE id=$1`,
    [id],
  )
  return row ? formatLocalArticleRow(row) : null
}
export async function readPolicies(
  params: URLSearchParams,
): Promise<PageResult<Policy>> {
  const where: string[] = [],
    values: unknown[] = []
  // 预筛相关度 <2 的（停水通知、民生提示类）默认不出现在政策库任何视图；
  // 保留在库里用于去重与信源监控，直链访问不受影响。
  where.push('triage_relevance >= 2')
  const sourceRef = params.get('sourceRef') || ''
  if (sourceRef && !/^policy:[a-f0-9]{32}$/.test(sourceRef))
    throw new Error('Invalid source')
  const search = (params.get('search') || '').trim().slice(0, 300)
  const searchWhere = buildContentSearch(search, 'policies')
  if (searchWhere) {
    values.push(...searchWhere.values)
    where.push(searchWhere.where)
  }
  if (sourceRef) {
    values.push(sourceRef.slice(7))
    where.push(`md5(site_key)=$${values.length}`)
  }
  for (const key of ['region', 'stage', 'instrument_type'] as const) {
    const value = params.get(key)
    if (value) {
      values.push(value)
      where.push(`${key}=$${values.length}`)
    }
  }
  if (params.get('mode') === 'analyzed') where.push('enriched_at IS NOT NULL')
  if (params.get('mode') === 'relevant')
    where.push('ai_relevance >= 4 AND enriched_at IS NOT NULL')
  return readCursorPage<Policy>('policies', params, {
    table: 'policy_documents',
    fields: policyFields + (searchWhere?.select || ''),
    where,
    values,
    time: "COALESCE(published_at,'0001-01-01'::timestamptz)",
    created: 'first_seen_at',
    rank: searchWhere ? 'CASE WHEN title ILIKE $1 THEN 0 ELSE 1 END' : '0::int',
  })
}

export async function readPolicy(id: string) {
  const [policy] = await query<Policy>(
    `SELECT ${policyFields},full_text FROM policy_documents WHERE id=$1`,
    [id],
  )
  return policy || null
}
export async function policyFacets() {
  return query<{
    region: string | null
    stage: string | null
    instrument_type: string | null
  }>('SELECT DISTINCT region,stage,instrument_type FROM policy_documents WHERE triage_relevance >= 2')
}
export async function signalSources() {
  return query<{ source: string }>(
    "SELECT DISTINCT source_feed_name AS source FROM articles WHERE COALESCE(source_feed_name,'') <> '' ORDER BY source_feed_name",
  )
}
export async function readClusters() {
  return query<Cluster>(
    `SELECT sc.id,sc.label,sc.summary,sc.status,COALESCE(linked.article_count,0)::int AS article_count,
      COALESCE(linked.source_count,0)::int AS source_count,sc.entities,sc.watch_keywords,sc.updated_at
    FROM signal_clusters sc
    LEFT JOIN (
      SELECT ca.cluster_id,count(*)::int AS article_count,count(DISTINCT NULLIF(a.source_feed_id,''))::int AS source_count
      FROM signal_cluster_articles ca JOIN articles a ON a.id=ca.article_id GROUP BY ca.cluster_id
    ) linked ON linked.cluster_id=sc.id
    ORDER BY sc.updated_at DESC,sc.id DESC`,
  )
}
export async function readPredictions() {
  return query<Prediction>(
    `SELECT tp.*,sc.label AS cluster_label FROM trend_predictions tp LEFT JOIN signal_clusters sc ON sc.id=tp.signal_cluster_id ORDER BY tp.created_at DESC,tp.id DESC`,
  )
}
export async function readReviews() {
  return query<Review>(
    `SELECT pr.*,tp.prediction_title FROM prediction_reviews pr JOIN trend_predictions tp ON tp.id=pr.prediction_id ORDER BY pr.reviewed_at DESC`,
  )
}
export async function readInsightHistory() {
  return query<{ generated_at: string; data: GlobalInsights }>(
    'SELECT generated_at,data FROM global_insights ORDER BY generated_at DESC LIMIT 30',
  )
}
export const getJournal = cache(async (): Promise<JournalData> => {
  const issues: string[] = []
  async function attempt<T>(
    name: string,
    fn: () => Promise<T>,
    fallback: T,
  ): Promise<T> {
    try {
      return await fn()
    } catch (e) {
      console.error(
        `Journal: ${name} unavailable`,
        e instanceof Error ? e.message : e,
      )
      issues.push(name)
      return fallback
    }
  }
  const [
    stats,
    pStats,
    articles,
    policies,
    clusters,
    predictions,
    reviews,
    insights,
  ] = await Promise.all([
    attempt<ArticleStats | null>('文章统计', articleStats, null),
    attempt<PolicyStats | null>('政策统计', policyStats, null),
    attempt<Row[]>(
      '精选文章',
      async () => {
        if (process.env.API_SOURCE && process.env.API_SOURCE !== 'local')
          return diverseArticles((await loadIcArticles()) as Row[], 8)
        return diverseArticles(
          (
            await query(
              `SELECT ${articleFields} FROM articles WHERE importance_score >= 4 ORDER BY COALESCE(publish_time,created_at) DESC NULLS LAST,id DESC LIMIT 80`,
            )
          ).map(formatLocalArticleRow),
          8,
        )
      },
      [],
    ),
    attempt<Policy[]>(
      '政策文件',
      async () => {
        const rows = await query<Policy>(
          `SELECT ${policyFields} FROM policy_documents WHERE enriched_at IS NOT NULL AND ai_relevance>=4 ORDER BY published_at DESC NULLS LAST,ai_relevance DESC LIMIT 16`,
        )
        const seen = new Set<string>()
        return rows
          .filter((p) => {
            const key = p.title.replace(/[《》\s]/g, '').replace(/发布$/, '')
            if (seen.has(key)) return false
            seen.add(key)
            return true
          })
          .slice(0, 3)
      },
      [],
    ),
    attempt<Cluster[]>('专题', readClusters, []),
    attempt<Prediction[]>('预测', readPredictions, []),
    attempt<Review[]>('复盘', readReviews, []),
    attempt<GlobalInsights | null>(
      '全局洞察',
      async () => {
        const [row] = await query<{
          data: GlobalInsights
          generated_at: string
        }>(
          'SELECT data,generated_at FROM global_insights ORDER BY generated_at DESC LIMIT 1',
        )
        return row ? { ...row.data, generated_at: row.generated_at } : null
      },
      null,
    ),
  ])
  return {
    stats,
    policyStats: pStats,
    articles,
    policies,
    clusters,
    predictions,
    reviews,
    insights,
    issues,
    loadedAt: new Date().toISOString(),
  }
})
export async function topicArticles(id: number) {
  const rows = await query(
    `SELECT a.*,COALESCE(a.publish_time,a.created_at) AS display_time FROM articles a JOIN signal_cluster_articles ca ON ca.article_id=a.id WHERE ca.cluster_id=$1 ORDER BY COALESCE(a.publish_time,a.created_at) DESC NULLS LAST,a.id DESC LIMIT 30`,
    [id],
  )
  return rows.map(formatLocalArticleRow)
}
export async function relatedPolicies(terms: string[]) {
  const useful = [
    ...new Set(
      terms.map((s) => s.trim()).filter((s) => s.length >= 2 && s.length <= 60),
    ),
  ].slice(0, 6)
  if (!useful.length) return []
  return query<Policy>(
    `SELECT ${policyFields} FROM policy_documents WHERE triage_relevance >= 2 AND enriched_at IS NOT NULL AND (title ILIKE ANY($1::text[]) OR summary ILIKE ANY($1::text[])) ORDER BY ai_relevance DESC NULLS LAST,published_at DESC NULLS LAST LIMIT 5`,
    [useful.map((s) => `%${s.replace(/[%_\\]/g, '\\$&')}%`)],
  )
}
export async function sourceHealth() {
  const issues: string[] = []
  const settled = await Promise.allSettled([
    query<SourceHealth>(
      `SELECT site_name AS name,'政策' AS kind,last_status AS status,last_run_at AS last_run,last_success_at AS last_success,last_item_count AS fetched,last_duration_ms AS duration_ms,consecutive_empty_runs AS empty_runs FROM policy_source_state ORDER BY last_run_at DESC NULLS LAST`,
    ),
    query<SourceHealth>(
      `SELECT name,'科技' AS kind,status,last_run,fetched,duration_ms FROM (SELECT DISTINCT ON (feed_url) feed_url AS name,status,ran_at AS last_run,fetched,duration_ms FROM feed_stats ORDER BY feed_url,ran_at DESC,id DESC) s ORDER BY last_run DESC LIMIT 300`,
    ),
  ])
  const sources = settled.flatMap((r, i) => {
    if (r.status === 'fulfilled') return r.value
    issues.push(i === 0 ? '政策采集记录' : '科技采集记录')
    return []
  })
  return { sources, issues }
}
export async function collectionTrend() {
  return query<{
    day: string
    articles: number
    policies: number
  }>(`WITH days AS (
    SELECT generate_series((now() AT TIME ZONE 'Asia/Shanghai')::date-13,(now() AT TIME ZONE 'Asia/Shanghai')::date,'1 day')::date AS day
  ), a AS (SELECT (created_at AT TIME ZONE 'Asia/Shanghai')::date AS day,count(*)::int AS n FROM articles GROUP BY 1),
  p AS (SELECT (first_seen_at AT TIME ZONE 'Asia/Shanghai')::date AS day,count(*)::int AS n FROM policy_documents GROUP BY 1)
  SELECT to_char(days.day,'MM/DD') AS day,COALESCE(a.n,0) AS articles,COALESCE(p.n,0) AS policies FROM days LEFT JOIN a USING(day) LEFT JOIN p USING(day) ORDER BY days.day`)
}

function articleMatch(row: Row, search: string) {
  const fields: [string, string | undefined][] = [
    ['标题', row.title],
    ['来源', row.source],
    ['摘要', row.core_event],
    ['隐藏信号', row.hidden_signal],
    ['判断依据', row.reason],
    ['行动建议', row.actionable],
    ['预测', row.prediction],
    ['标签', row.tags?.join(' ')],
    ['实体', row.entities?.join(' ')],
    ['正文', row.full_text],
  ]
  for (const [label, text] of fields) {
    const index = text?.toLowerCase().indexOf(search.toLowerCase()) ?? -1
    if (text && index >= 0) {
      const start = Math.max(0, index - 50)
      return {
        search_field: label,
        search_excerpt: (start > 0 ? '…' : '') + text.slice(start, start + 240),
      }
    }
  }
  return null
}

// Keyset ordering includes relevance, microsecond timestamp and id. New insertions
// are excluded from the current reading window until the reader chooses refresh.
async function readCursorPage<T extends QueryResultRow = QueryResultRow>(
  kind: SearchScope,
  params: URLSearchParams,
  options: {
    table: string
    fields: string
    where: string[]
    values: unknown[]
    time: string
    created: string
    rank: string
  },
): Promise<PageResult<T>> {
  const signature = cursorQuery(kind, params),
    cursor = decodeCursor(params.get('cursor'), signature)
  const snapshot = cursor?.snapshot || new Date().toISOString(),
    page = pageNumber(params)
  const { table, fields, time, created, rank } = options
  const values = [...options.values, snapshot],
    where = [
      ...options.where,
      `(${created} IS NULL OR ${created} <= $${options.values.length + 1}::timestamptz)`,
    ]
  const countSql = `WHERE ${where.join(' AND ')}`,
    countValues = [...values]
  const boundary = cursorBoundary(values, cursor, rank, time)
  if (boundary) where.push(boundary)
  const offset = !cursor && page > 1 ? ` OFFSET $${values.length + 1}` : ''
  if (offset) values.push((page - 1) * 30)
  const [counts, rows] = await Promise.all([
    query<{ total: number }>(
      `SELECT count(*)::int AS total FROM ${table} ${countSql}`,
      countValues,
    ),
    query<T & { cursor_time: string; cursor_rank: number }>(
      `SELECT ${fields},to_char(${time} AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS cursor_time,(${rank}) AS cursor_rank FROM ${table} WHERE ${where.join(' AND ')} ORDER BY (${rank}) ASC,${time} DESC,id DESC LIMIT 31${offset}`,
      values,
    ),
  ])
  const visible = rows.slice(0, 30),
    last = visible.at(-1),
    hasMore = rows.length > 30
  return {
    data: visible.map((row) => {
      const { cursor_time, cursor_rank, ...item } = row
      return item as unknown as T
    }),
    total: counts[0].total,
    page,
    hasMore,
    snapshot,
    nextCursor:
      hasMore && last
        ? encodeCursor({
            v: 1,
            query: signature,
            snapshot,
            rank: last.cursor_rank,
            time: last.cursor_time,
            id: last.id,
          })
        : null,
  }
}

// Shared server-only connection access for the monitoring read model.
export { query as queryJournal }

export async function topicName(id: string) {
  if (!/^[1-9]\d*$/.test(id) || Number(id) > 2147483647) return null
  const [topic] = await query<{ label: string }>(
    'SELECT label FROM signal_clusters WHERE id=$1',
    [Number(id)],
  )
  return topic?.label || null
}

export async function readerSourceName(ref: string) {
  if (!/^(tech|policy):[a-f0-9]{32}$/.test(ref)) return null
  const tech = ref.startsWith('tech:'),
    hash = ref.split(':')[1]
  const [row] = await query<{ name: string }>(
    tech
      ? 'SELECT source_feed_name AS name FROM articles WHERE md5(source_feed_id)=$1 ORDER BY created_at DESC LIMIT 1'
      : 'SELECT site_name AS name FROM policy_documents WHERE md5(site_key)=$1 ORDER BY first_seen_at DESC LIMIT 1',
    [hash],
  )
  return row?.name || null
}
