import { Pool, type QueryResultRow } from 'pg'
import { cache } from 'react'
import {
  formatLocalArticleRow,
  buildArticleSearchWhere,
} from './localArticleRows'
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
): Promise<PageResult<Row>> {
  const page = pageNumber(params)
  const search = (params.get('search') || '').trim().slice(0, 300)
  const source = params.get('source') || '',
    tag = params.get('tag') || '',
    date = params.get('date') || ''
  const mode = params.get('mode') || 'all'
  if (
    date &&
    (!/^\d{4}-\d{2}-\d{2}$/.test(date) ||
      !Number.isFinite(Date.parse(date)) ||
      new Date(date).toISOString().slice(0, 10) !== date)
  )
    throw new Error('Invalid date')
  if (process.env.API_SOURCE && process.env.API_SOURCE !== 'local') {
    let rows = (await loadIcArticles()) as Row[]
    rows = rows.filter(
      (r) =>
        (!search ||
          JSON.stringify(r).toLowerCase().includes(search.toLowerCase())) &&
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
    rows.sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime())
    return {
      data: rows.slice((page - 1) * 30, page * 30),
      total: rows.length,
      page,
      hasMore: page * 30 < rows.length,
    }
  }
  const values: unknown[] = [],
    where: string[] = []
  const add = (clause: string, value: unknown) => {
    values.push(value)
    where.push(clause.replace('?', `$${values.length}`))
  }
  const searchWhere = buildArticleSearchWhere(search, values.length + 1)
  if (searchWhere) {
    values.push(searchWhere.value)
    where.push(`(${searchWhere.sql} OR full_text ILIKE $${values.length})`)
  }
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
  const sql = where.length ? `WHERE ${where.join(' AND ')}` : ''
  const [counts, rows] = await Promise.all([
    query<{ total: number }>(
      `SELECT count(*)::int AS total FROM articles ${sql}`,
      values,
    ),
    query(
      `SELECT ${articleFields} FROM articles ${sql} ORDER BY COALESCE(publish_time,created_at) DESC NULLS LAST, id DESC LIMIT 30 OFFSET $${values.length + 1}`,
      [...values, (page - 1) * 30],
    ),
  ])
  return {
    data: rows.map(formatLocalArticleRow),
    total: counts[0].total,
    page,
    hasMore: page * 30 < counts[0].total,
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
  const page = pageNumber(params)
  const where: string[] = [],
    values: unknown[] = []
  const search = params.get('search')?.trim().slice(0, 300)
  if (search) {
    values.push(`%${search}%`)
    where.push(
      `(title ILIKE $1 OR summary ILIKE $1 OR issuing_authority ILIKE $1 OR affected_parties::text ILIKE $1)`,
    )
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
  const sql = where.length ? `WHERE ${where.join(' AND ')}` : ''
  const [counts, rows] = await Promise.all([
    query<{ total: number }>(
      `SELECT count(*)::int AS total FROM policy_documents ${sql}`,
      values,
    ),
    query<Policy>(
      `SELECT ${policyFields} FROM policy_documents ${sql} ORDER BY published_at DESC NULLS LAST,id DESC LIMIT 30 OFFSET $${values.length + 1}`,
      [...values, (page - 1) * 30],
    ),
  ])
  return {
    data: rows,
    total: counts[0].total,
    page,
    hasMore: page * 30 < counts[0].total,
  }
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
  }>('SELECT DISTINCT region,stage,instrument_type FROM policy_documents')
}
export async function signalSources() {
  return query<{ source: string }>(
    "SELECT DISTINCT source_feed_name AS source FROM articles WHERE COALESCE(source_feed_name,'') <> '' ORDER BY source_feed_name",
  )
}
export async function readClusters() {
  return query<Cluster>(
    'SELECT id,label,summary,status,article_count,source_count,entities,watch_keywords,updated_at FROM signal_clusters ORDER BY updated_at DESC,id DESC',
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
    `SELECT a.*,COALESCE(a.publish_time,a.created_at) AS display_time FROM articles a JOIN signal_cluster_articles ca ON ca.article_id=a.id WHERE ca.cluster_id=$1 ORDER BY ca.relevance_score DESC NULLS LAST,a.publish_time DESC LIMIT 30`,
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
    `SELECT ${policyFields} FROM policy_documents WHERE enriched_at IS NOT NULL AND (title ILIKE ANY($1::text[]) OR summary ILIKE ANY($1::text[])) ORDER BY ai_relevance DESC NULLS LAST,published_at DESC NULLS LAST LIMIT 5`,
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
