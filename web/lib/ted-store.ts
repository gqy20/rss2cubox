import { randomUUID } from 'node:crypto'
import { queryJournal } from './journal-store'
import {
  assembleReport,
  isTedId,
  parseReport,
  publicReport,
  validateWindow,
  type TedCoverage,
  type TedIssue,
  type TedMaterials,
  type TedReport,
  type TedSource,
} from './ted'

// Lazy initialization on the first draft creation. Public reads never perform DDL.
export const TED_SCHEMA = `
CREATE TABLE IF NOT EXISTS ted_issues (
  id UUID PRIMARY KEY,
  issue_number INTEGER GENERATED ALWAYS AS IDENTITY UNIQUE,
  version INTEGER NOT NULL DEFAULT 1,
  draft JSONB NOT NULL,
  published JSONB,
  published_version INTEGER,
  published_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ted_revisions (
  issue_id UUID NOT NULL REFERENCES ted_issues(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  report JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (issue_id, version)
);
CREATE INDEX IF NOT EXISTS ted_issues_published_idx ON ted_issues(published_at DESC)
  WHERE published IS NOT NULL;
`

function missingTable(error: unknown) {
  return (error as { code?: string })?.code === '42P01'
}
export class TedConflictError extends Error {}

export async function listTedIssues(editor = false): Promise<TedIssue[]> {
  try {
    // List rows omit long bodies and source snapshots; full content is loaded on demand.
    return await queryJournal<TedIssue>(`
      SELECT id,issue_number,version,published_version,published_at,updated_at,created_at,
        jsonb_build_object('title',r->'title','intro',r->'intro','tags',r->'tags',
          'start_date',r->'start_date','end_date',r->'end_date','cover',r->'cover',
          'topics',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',t->'id','title',t->'title')),'[]'::jsonb)
                    FROM jsonb_array_elements(r->'topics') t)) AS report
      FROM (SELECT *,${editor ? 'draft' : 'published'} AS r FROM ted_issues
        ${editor ? '' : 'WHERE published IS NOT NULL'}) issues
      ORDER BY ${editor ? 'updated_at' : 'issue_number'} DESC LIMIT 200`)
  } catch (error) {
    if (missingTable(error)) return []
    throw error
  }
}

export async function readTedIssue(
  id: string,
  editor = false,
): Promise<TedIssue | null> {
  if (!isTedId(id)) return null
  try {
    const [issue] = await queryJournal<TedIssue>(
      `
      SELECT id,issue_number,version,published_version,published_at,updated_at,created_at,
        ${editor ? 'draft' : 'published'} AS report
      FROM ted_issues WHERE id=$1 ${editor ? '' : 'AND published IS NOT NULL'}`,
      [id],
    )
    if (!issue) return null
    if (!editor) issue.report = publicReport(issue.report)
    return issue
  } catch (error) {
    if (missingTable(error)) return null
    throw error
  }
}

/** Reading pages show prepared reports, with host notes removed from every response. */
export async function listTedAudienceIssues(): Promise<TedIssue[]> {
  try {
    return await queryJournal<TedIssue>(`
      SELECT id,issue_number,version,published_version,published_at,updated_at,created_at,
        jsonb_build_object('title',draft->'title','intro',draft->'intro','tags',draft->'tags',
          'start_date',draft->'start_date','end_date',draft->'end_date','cover',draft->'cover',
          'edition_date',draft->'edition_date','live_at',draft->'live_at',
          'topics',(SELECT COALESCE(jsonb_agg(jsonb_build_object('id',t->'id','title',t->'title')),'[]'::jsonb)
                    FROM jsonb_array_elements(draft->'topics') t)) AS report
      FROM ted_issues
      WHERE NULLIF(btrim(draft->>'title'),'') IS NOT NULL
        AND jsonb_array_length(draft->'topics')>0
      ORDER BY issue_number DESC LIMIT 200`)
  } catch (error) {
    if (missingTable(error)) return []
    throw error
  }
}

export async function readTedAudienceIssue(
  id: string,
): Promise<TedIssue | null> {
  const issue = await readTedIssue(id, true)
  if (!issue?.report.title.trim() || !issue.report.topics.length) return null
  return { ...issue, report: publicReport(issue.report) }
}

export async function readTedMaterials(
  startDate: string,
  endDate: string,
  cutoff = new Date().toISOString(),
): Promise<TedMaterials> {
  const window = validateWindow(startDate, endDate)
  const params = [window.start, window.end, cutoff]
  const [coverageRows, articleRows, policyRows] = await Promise.all([
    queryJournal<TedCoverage>(
      `
      WITH a AS (
        SELECT source_feed_id,created_at,publish_time,
          (COALESCE(hidden_signal,'')<>'' OR COALESCE(reason,'')<>'' OR COALESCE(actionable,'')<>'') AS analyzed
        FROM articles WHERE COALESCE(publish_time,created_at)>=$1::timestamptz
          AND COALESCE(publish_time,created_at)<$2::timestamptz AND created_at<=$3::timestamptz
          AND COALESCE(publish_time,created_at)<=$3::timestamptz
      ), p AS (
        SELECT site_key,first_seen_at,published_at,enriched_at FROM policy_documents
        WHERE COALESCE(published_at,first_seen_at)>=$1::timestamptz
          AND COALESCE(published_at,first_seen_at)<$2::timestamptz AND first_seen_at<=$3::timestamptz
          AND COALESCE(published_at,first_seen_at)<=$3::timestamptz
      ) SELECT (SELECT count(*)::int FROM a) AS articles,(SELECT count(*)::int FROM p) AS policies,
        ((SELECT count(*) FROM a WHERE analyzed)+(SELECT count(*) FROM p WHERE enriched_at IS NOT NULL))::int AS analyzed,
        ((SELECT count(DISTINCT NULLIF(source_feed_id,'')) FROM a)+(SELECT count(DISTINCT site_key) FROM p))::int AS sources,
        (SELECT max(created_at) FROM articles WHERE created_at<=$3::timestamptz) AS latest_article,
        (SELECT max(first_seen_at) FROM policy_documents WHERE first_seen_at<=$3::timestamptz) AS latest_policy`,
      params,
    ),
    queryJournal<TedSource>(
      `
      WITH ranked AS (
        SELECT a.id,'article'::text AS kind,a.title,a.url,COALESCE(a.source_feed_name,'') AS publisher,
          COALESCE(a.publish_time,a.created_at) AS published_at,
          CASE WHEN a.publish_time IS NULL THEN 'collected' ELSE 'published' END AS date_basis,
          COALESCE(NULLIF(a.hidden_signal,''),NULLIF(a.reason,''),a.description,'') AS summary,
          ''::text AS reason,c.id AS cluster_id,c.label AS cluster_label,
          a.importance_score,a.novelty_score,
          row_number() OVER (PARTITION BY COALESCE(c.id::text,a.source_feed_id,a.id)
            ORDER BY a.importance_score DESC NULLS LAST,a.novelty_score DESC NULLS LAST,a.publish_time DESC) AS rank
        FROM articles a LEFT JOIN LATERAL (
          SELECT sc.id,sc.label FROM signal_cluster_articles ca JOIN signal_clusters sc ON sc.id=ca.cluster_id
          WHERE ca.article_id=a.id AND sc.status NOT IN ('invalid','archived')
          ORDER BY ca.relevance_score DESC NULLS LAST,sc.id LIMIT 1
        ) c ON true
        WHERE COALESCE(a.publish_time,a.created_at)>=$1::timestamptz
          AND COALESCE(a.publish_time,a.created_at)<$2::timestamptz
          AND a.created_at<=$3::timestamptz AND COALESCE(a.publish_time,a.created_at)<=$3::timestamptz
          AND a.url ~ '^https?://' AND (COALESCE(a.hidden_signal,'')<>'' OR COALESCE(a.reason,'')<>'' OR COALESCE(a.actionable,'')<>'')
      ) SELECT id,kind,title,url,publisher,published_at,date_basis,left(summary,6000) AS summary,reason,cluster_id,cluster_label
        FROM ranked ORDER BY rank,importance_score DESC NULLS LAST,novelty_score DESC NULLS LAST,published_at DESC LIMIT 180`,
      params,
    ),
    queryJournal<TedSource>(
      `
      SELECT id,'policy'::text AS kind,title,url,COALESCE(site_name,'') AS publisher,
        COALESCE(published_at,first_seen_at) AS published_at,
        CASE WHEN published_at IS NULL THEN 'collected' ELSE 'published' END AS date_basis,
        left(COALESCE(NULLIF(summary,''),ai_relevance_reason,''),6000) AS summary,''::text AS reason
      FROM policy_documents WHERE COALESCE(published_at,first_seen_at)>=$1::timestamptz
        AND COALESCE(published_at,first_seen_at)<$2::timestamptz AND first_seen_at<=$3::timestamptz
        AND COALESCE(published_at,first_seen_at)<=$3::timestamptz
        AND enriched_at IS NOT NULL AND ai_relevance>=2 AND url ~ '^https?://'
      ORDER BY ai_relevance DESC NULLS LAST,published_at DESC NULLS LAST,id LIMIT 60`,
      params,
    ),
  ])
  return {
    start_date: startDate,
    end_date: endDate,
    cutoff_at: cutoff,
    coverage: coverageRows[0],
    materials: [...articleRows, ...policyRows],
    limit: 240,
  }
}

export async function createTedIssue(startDate: string, endDate: string) {
  const packet = await readTedMaterials(startDate, endDate)
  const report = parseReport(assembleReport(packet))
  await queryJournal(TED_SCHEMA)
  const [row] = await queryJournal<{ id: string }>(
    'INSERT INTO ted_issues (id,draft) VALUES ($1,$2::jsonb) RETURNING id',
    [randomUUID(), JSON.stringify(report)],
  )
  return readTedIssue(row.id, true)
}

export async function saveTedIssue(
  id: string,
  version: number,
  input: unknown,
  publish: boolean,
) {
  const report = parseReport(input, publish)
  const previous = await readTedIssue(id, true)
  if (!previous || previous.version !== version)
    throw new TedConflictError(
      '这份报告已在其他窗口更新。请先复制未保存文字，再重新载入。',
    )
  // The selection window and aggregate counts describe the original material snapshot.
  const draft: TedReport = {
    ...report,
    start_date: previous.report.start_date,
    end_date: previous.report.end_date,
    cutoff_at: previous.report.cutoff_at,
    coverage: previous.report.coverage,
    preparation: 'edited',
  }
  const published = publicReport(draft)
  // One statement: compare-and-swap, snapshot publication, and revision are atomic.
  const rows = await queryJournal<{ id: string }>(
    `
    WITH saved AS (
      UPDATE ted_issues SET draft=$3::jsonb,version=version+1,updated_at=now(),
        published=CASE WHEN $4::boolean THEN $5::jsonb ELSE published END,
        published_at=CASE WHEN $4::boolean THEN now() ELSE published_at END,
        published_version=CASE WHEN $4::boolean THEN version+1 ELSE published_version END
      WHERE id=$1 AND version=$2 RETURNING id,version
    ), revision AS (
      INSERT INTO ted_revisions (issue_id,version,report)
      SELECT id,version,$5::jsonb FROM saved WHERE $4::boolean RETURNING issue_id
    ) SELECT id FROM saved`,
    [id, version, JSON.stringify(draft), publish, JSON.stringify(published)],
  )
  if (!rows.length)
    throw new TedConflictError(
      '报告已更新，本次修改没有覆盖其他编辑。请重新载入。',
    )
  return readTedIssue(id, true)
}

export async function tedDataFreshness() {
  const [row] = await queryJournal<{
    latest_article: string | null
    latest_policy: string | null
  }>(`
    SELECT (SELECT max(created_at) FROM articles) AS latest_article,
      (SELECT max(first_seen_at) FROM policy_documents) AS latest_policy`)
  return row
}

export async function listTedRevisions(id: string) {
  return queryJournal<{ version: number; created_at: string }>(
    'SELECT version,created_at FROM ted_revisions WHERE issue_id=$1 ORDER BY version DESC',
    [id],
  )
}
