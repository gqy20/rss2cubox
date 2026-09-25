import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { queryJournal } from './journal-store'
import { memoize } from './memo'
import { formatLocalArticleRow } from './localArticleRows'
import {
  parseFeedRegistry,
  parsePolicyRegistry,
  redactAddress,
  redactError,
  runStreak,
  sourceDomain,
} from './monitor-utils'
import type {
  MonitorSnapshot,
  MonitorSource,
  SourceSpec,
  SourceRun,
  MonitorDetail,
  SourceAttempt,
  SourceKind,
} from './monitor-types'
import type { Policy } from './journal-types'
const sourceId = (kind: SourceKind, key: string) =>
  `${kind}:${createHash('md5').update(key).digest('hex')}`
type Registry = {
  specs: SourceSpec[]
  techAvailable: boolean
  policyAvailable: boolean
}
async function optionalFile(file: string) {
  try {
    return await readFile(file, 'utf8')
  } catch {
    return null
  }
}
// Registry parses .env + feeds.txt + policy_sources.toml from disk; the files
// change at deploy time, so a minute of staleness is harmless.
const registry = memoize(async (): Promise<Registry> => {
  let root = path.resolve(process.cwd(), '..')
  if ((await optionalFile(path.resolve(process.cwd(), 'feeds.txt'))) !== null)
    root = process.cwd()
  const config = await optionalFile(path.join(root, '.env'))
  const setting = (key: string) => {
    const raw = config
      ?.match(new RegExp(`^\\s*(?:export\\s+)?${key}\\s*=\\s*(.*)$`, 'm'))?.[1]
      ?.trim()
    return raw === undefined
      ? process.env[key]
      : raw
          .split(' # ')[0]
          .trim()
          .replace(/^(['"])(.*)\1$/, '$2')
  }
  const [feedText, policyText] = await Promise.all([
    optionalFile(path.resolve(root, setting('FEEDS_FILE') || 'feeds.txt')),
    optionalFile(path.join(root, 'policy_sources.toml')),
  ])
  let policies: SourceSpec[] = []
  let policyAvailable = policyText !== null
  try {
    if (policyText !== null) policies = parsePolicyRegistry(policyText)
  } catch {
    policyAvailable = false
  }
  return {
    specs: [
      ...(feedText !== null
        ? parseFeedRegistry(feedText, setting('FEED_SECTIONS_DISABLE') || '')
        : []),
      ...policies,
    ],
    techAvailable: feedText !== null,
    policyAvailable,
  }
}, 60_000)
export const techRunsSql = `WITH rounds AS (
 SELECT feed_url,COALESCE(NULLIF(run_id,''),'record-'||id::text) AS run_key,max(ran_at) AS at,
 CASE WHEN bool_or(status='ok') THEN 'ok' WHEN bool_or(status='empty') THEN 'empty'
 WHEN bool_or(status IN ('failed','timeout','parse_error')) THEN 'failed' ELSE 'skipped' END AS status,
 COALESCE(max(fetched) FILTER(WHERE status='ok'),0)::int AS fetched,COALESCE(sum(duration_ms),0)::int AS duration_ms,count(*)::int AS attempts,
 CASE WHEN bool_or(status IN ('ok','empty')) THEN NULL ELSE (array_agg(error_msg ORDER BY ran_at DESC,id DESC) FILTER(WHERE error_msg IS NOT NULL))[1] END AS error
 FROM feed_stats GROUP BY feed_url,COALESCE(NULLIF(run_id,''),'record-'||id::text)
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY feed_url ORDER BY at DESC,run_key DESC) AS rn,
 max(at) FILTER(WHERE status IN ('ok','empty')) OVER(PARTITION BY feed_url) AS last_success FROM rounds
)
SELECT feed_url,max(last_success) AS last_success,
 jsonb_agg(jsonb_build_object('id',run_key,'at',at,'status',status,'fetched',fetched,'durationMs',duration_ms,'attempts',attempts,'error',error) ORDER BY at DESC,run_key DESC) AS runs
FROM ranked WHERE rn<=12 GROUP BY feed_url`
type TechRecord = {
  feed_url: string
  last_success: string | null
  runs: SourceRun[]
}
type ContentStats = {
  key: string
  name: string | null
  articles: number
  analyzed: number
  scored: number
  high: number
  last_published: string | null
}
type PolicyState = {
  site_key: string
  site_name: string
  region: string | null
  last_status: string | null
  last_run_at: string | null
  last_success_at: string | null
  last_item_count: number
  last_duration_ms: number
  last_error: string | null
  consecutive_empty_runs: number
}
function makeAttempt(issues: string[]) {
  return async <T>(label: string, fn: () => Promise<T>, fallback: T) => {
    try {
      return await fn()
    } catch {
      issues.push(label)
      return fallback
    }
  }
}
// md5 source ids are not reversible, so details need a known-key lookup.
// Cheap DISTINCT scans + the registry, cached briefly — the full snapshot
// aggregation is far too heavy to rebuild for every detail request.
let keyCache: {
  at: number
  map: Map<string, { kind: SourceKind; key: string }>
} | null = null
const KEY_CACHE_MS = 60_000
async function sourceKeys() {
  if (keyCache && Date.now() - keyCache.at < KEY_CACHE_MS) return keyCache.map
  const config = await registry()
  const [tech, policy] = await Promise.all([
    queryJournal<{ key: string }>(
      `SELECT DISTINCT feed_url AS key FROM feed_stats
       UNION SELECT DISTINCT source_feed_id AS key FROM articles WHERE COALESCE(source_feed_id,'')<>''`,
    ).catch(() => []),
    queryJournal<{ key: string }>(
      `SELECT site_key AS key FROM policy_source_state
       UNION SELECT DISTINCT site_key AS key FROM policy_documents`,
    ).catch(() => []),
  ])
  const map = new Map<string, { kind: SourceKind; key: string }>()
  const add = (kind: SourceKind, key: string) => {
    if (key) map.set(sourceId(kind, key), { kind, key })
  }
  config.specs.forEach((s) => add(s.kind, s.key))
  tech.forEach((r) => add('tech', r.key))
  policy.forEach((r) => add('policy', r.key))
  keyCache = { at: Date.now(), map }
  return map
}
async function snapshotWithKeys() {
  const issues: string[] = []
  const attempt = makeAttempt(issues)
  const [config, tech, articleStats, policyStates, policyStats] =
    await Promise.all([
      registry(),
      attempt<TechRecord[]>(
        '科技采集记录',
        () => queryJournal(techRunsSql),
        [],
      ),
      attempt<ContentStats[]>(
        '文章产出统计',
        () =>
          queryJournal(`SELECT source_feed_id AS key,(array_agg(source_feed_name ORDER BY created_at DESC) FILTER(WHERE COALESCE(source_feed_name,'')<>''))[1] AS name,count(*)::int AS articles,
   count(*) FILTER(WHERE COALESCE(hidden_signal,'')<>'' OR COALESCE(reason,'')<>'' OR COALESCE(actionable,'')<>'')::int AS analyzed,
   count(*) FILTER(WHERE importance_score BETWEEN 1 AND 5)::int AS scored,count(*) FILTER(WHERE importance_score BETWEEN 4 AND 5)::int AS high,max(publish_time) AS last_published
   FROM articles WHERE COALESCE(source_feed_id,'')<>'' GROUP BY source_feed_id`),
        [],
      ),
      attempt<PolicyState[]>(
        '政策采集记录',
        () => queryJournal('SELECT * FROM policy_source_state'),
        [],
      ),
      attempt<ContentStats[]>(
        '政策产出统计',
        () =>
          queryJournal(`SELECT site_key AS key,max(site_name) AS name,count(*)::int AS articles,count(*) FILTER(WHERE enriched_at IS NOT NULL)::int AS analyzed,
   count(*) FILTER(WHERE enriched_at IS NOT NULL AND ai_relevance BETWEEN 1 AND 5)::int AS scored,count(*) FILTER(WHERE enriched_at IS NOT NULL AND ai_relevance BETWEEN 4 AND 5)::int AS high,max(published_at) AS last_published
   FROM policy_documents GROUP BY site_key`),
        [],
      ),
    ])
  if (!config.techAvailable) issues.push('科技源配置（仅显示已有记录）')
  if (!config.policyAvailable) issues.push('政策源配置（仅显示已有记录）')
  const specs = new Map(config.specs.map((s) => [`${s.kind}:${s.key}`, s]))
  const techMap = new Map(tech.map((s) => [s.feed_url, s])),
    policyMap = new Map(policyStates.map((s) => [s.site_key, s]))
  const contentMap = new Map<string, ContentStats>([
    ...articleStats.map((s) => [`tech:${s.key}`, s] as const),
    ...policyStats.map((s) => [`policy:${s.key}`, s] as const),
  ])
  const keys = new Map<string, { kind: SourceKind; key: string }>()
  const add = (kind: SourceKind, key: string) =>
    keys.set(`${kind}:${key}`, { kind, key })
  config.specs.forEach((s) => add(s.kind, s.key))
  tech.forEach((s) => add('tech', s.feed_url))
  articleStats.forEach((s) => add('tech', s.key))
  policyStates.forEach((s) => add('policy', s.site_key))
  policyStats.forEach((s) => add('policy', s.key))
  const sources = [...keys.entries()].map(
    ([mapKey, { kind, key }]): MonitorSource => {
      const spec = specs.get(mapKey),
        stats = contentMap.get(mapKey),
        techSource = techMap.get(key),
        policySource = policyMap.get(key)
      const available =
        kind === 'tech' ? config.techAvailable : config.policyAvailable
      const configuration = spec
        ? spec.enabled
          ? 'enabled'
          : 'disabled'
        : available
          ? 'historical'
          : 'unknown'
      const unavailable = issues.includes(
        kind === 'tech' ? '科技采集记录' : '政策采集记录',
      )
      const runs: SourceRun[] =
        kind === 'tech'
          ? techSource?.runs || []
          : policySource?.last_run_at
            ? [
                {
                  id: policySource.last_run_at,
                  at: policySource.last_run_at,
                  status:
                    policySource.last_status === 'ok'
                      ? 'ok'
                      : policySource.last_status === 'empty'
                        ? 'empty'
                        : policySource.last_status === 'skipped'
                          ? 'skipped'
                          : 'failed',
                  fetched: policySource.last_item_count || 0,
                  durationMs: policySource.last_duration_ms || 0,
                  attempts: 1,
                  error: policySource.last_error,
                },
              ]
            : []
      const cleanRuns = runs.map((r) => ({ ...r, error: redactError(r.error) }))
      const status =
        configuration === 'disabled'
          ? 'disabled'
          : configuration === 'historical'
            ? 'archived'
            : unavailable
              ? 'unavailable'
              : runs[0]?.status || 'never'
      const address = redactAddress(spec?.url || (kind === 'tech' ? key : '')),
        id = sourceId(kind, key)
      return {
        id,
        kind,
        name:
          spec?.name ||
          stats?.name ||
          policySource?.site_name ||
          sourceDomain(address) ||
          key,
        domain: sourceDomain(address),
        address,
        configuration,
        status,
        runs: cleanRuns,
        lastRun: runs[0]?.at || null,
        lastSuccess:
          kind === 'tech'
            ? techSource?.last_success || null
            : policySource?.last_success_at || null,
        lastPublished: stats?.last_published || null,
        failureStreak: runStreak(cleanRuns, 'failed'),
        emptyStreak:
          kind === 'policy'
            ? policySource?.consecutive_empty_runs || 0
            : runStreak(cleanRuns, 'empty'),
        recovered: runs[0]?.status === 'ok' && runs[1]?.status === 'failed',
        articles: stats?.articles || 0,
        analyzed: stats?.analyzed || 0,
        scored: stats?.scored || 0,
        high: stats?.high || 0,
        region: spec?.region || policySource?.region || undefined,
        contentAvailable: !issues.includes(
          kind === 'tech' ? '文章产出统计' : '政策产出统计',
        ),
      }
    },
  )
  return { sources, issues, loadedAt: new Date().toISOString() }
}
// The ops view tolerates a short snapshot lag; the page renders loadedAt.
export const readMonitorSnapshot = memoize(
  (): Promise<MonitorSnapshot> => snapshotWithKeys(),
  30_000,
)
export async function readMonitorDetail(
  id: string,
): Promise<MonitorDetail | null> {
  if (!/^(tech|policy):[a-f0-9]{32}$/.test(id)) return null
  const reference = (await sourceKeys()).get(id)
  if (!reference) return null
  const { kind, key } = reference,
    issues: string[] = []
  const attempt = makeAttempt(issues)
  if (kind === 'policy') {
    const rows = await attempt<Policy[]>(
      '政策内容',
      () =>
        queryJournal(
          `SELECT id,title,url,site_name,region,stage,published_at,summary,ai_relevance,enriched_at FROM policy_documents WHERE site_key=$1 ORDER BY published_at DESC NULLS LAST,id DESC LIMIT 12`,
          [key],
        ),
      [],
    )
    const high = await attempt<Policy[]>(
      '高相关政策',
      () =>
        queryJournal(
          `SELECT id,title,url,site_name,region,stage,published_at,summary,ai_relevance,enriched_at FROM policy_documents WHERE site_key=$1 AND enriched_at IS NOT NULL AND ai_relevance BETWEEN 4 AND 5 ORDER BY published_at DESC NULLS LAST,id DESC LIMIT 12`,
          [key],
        ),
      [],
    )
    return {
      articles: [],
      highArticles: [],
      policies: rows,
      highPolicies: high,
      topics: [],
      attempts: [],
      issues,
    }
  }
  const fields = `id,title,url,source_feed_id,source_feed_name,description,importance_score,hidden_signal,reason,actionable,tags,COALESCE(publish_time,created_at) AS display_time`
  const [latest, high, topics, attempts] = await Promise.all([
    attempt(
      '最新文章',
      () =>
        queryJournal(
          `SELECT ${fields} FROM articles WHERE source_feed_id=$1 ORDER BY COALESCE(publish_time,created_at) DESC,id DESC LIMIT 12`,
          [key],
        ),
      [],
    ),
    attempt(
      '重点文章',
      () =>
        queryJournal(
          `SELECT ${fields} FROM articles WHERE source_feed_id=$1 AND importance_score BETWEEN 4 AND 5 ORDER BY COALESCE(publish_time,created_at) DESC,id DESC LIMIT 12`,
          [key],
        ),
      [],
    ),
    attempt<{ id: number; label: string; articles: number }[]>(
      '关联专题',
      () =>
        queryJournal(
          `SELECT sc.id,sc.label,count(*)::int AS articles FROM signal_clusters sc JOIN signal_cluster_articles ca ON ca.cluster_id=sc.id JOIN articles a ON a.id=ca.article_id WHERE a.source_feed_id=$1 GROUP BY sc.id,sc.label ORDER BY count(*) DESC LIMIT 8`,
          [key],
        ),
      [],
    ),
    attempt<SourceAttempt[]>(
      '请求明细',
      () =>
        queryJournal(
          `SELECT COALESCE(NULLIF(run_id,''),'record-'||id::text) AS "runId",ran_at AS at,status,candidate_url AS address,duration_ms AS "durationMs",error_msg AS error FROM feed_stats WHERE feed_url=$1 ORDER BY ran_at DESC,id DESC LIMIT 100`,
          [key],
        ),
      [],
    ),
  ])
  return {
    articles: latest.map(formatLocalArticleRow),
    highArticles: high.map(formatLocalArticleRow),
    policies: [],
    highPolicies: [],
    topics,
    attempts: attempts.map((a) => ({
      ...a,
      address: redactAddress(a.address),
      error: redactError(a.error),
    })),
    issues,
  }
}
