import { queryJournal } from './journal-store'
import { readTedAudienceIssue } from './ted-store'
import { parseSourceAnalysis, type TedSourceDetail } from './ted'

export async function readTedSourceDetail(issueId: string, sourceId: string): Promise<TedSourceDetail | null> {
  const issue = await readTedAudienceIssue(issueId)
  const source = issue?.report.topics.flatMap((topic) => topic.sources).find((item) => item.id === sourceId)
  if (!source) return null
  const detail: TedSourceDetail = {
    source: { id: source.id, title: source.title, url: source.url, publisher: source.publisher, reason: source.reason },
    analysis: source.analysis || null,
    record_id: null,
  }
  const urls = [...new Set([source.url, source.url.replace(/\/$/, ''), source.url.replace(/\/$/, '') + '/'])]
  try {
    const [article] = await queryJournal<{
      id: string; importance_score: number | null; reason: string | null;
      hidden_signal: string | null; actionable: string | null; prediction: string | null; tags: string[];
    }>(`SELECT id,importance_score,reason,hidden_signal,actionable,prediction,tags FROM articles WHERE url=ANY($1::text[]) LIMIT 1`, [urls])
    if (article) {
      detail.record_id = article.id
      if (article.reason || article.hidden_signal || article.actionable || article.prediction)
        detail.analysis = parseSourceAnalysis({ ...article, kind: 'article',
          reason: article.reason || '', hidden_signal: article.hidden_signal || '',
          actionable: article.actionable || '', prediction: article.prediction || '',
          tags: Array.isArray(article.tags) ? article.tags : [],
        })
      return detail
    }
    const [policy] = await queryJournal<{
      id: string; ai_relevance: number | null; ai_relevance_reason: string | null;
      summary: string | null; source_quote: string | null; enriched_at: string | null;
    }>(`SELECT id,ai_relevance,ai_relevance_reason,summary,source_quote,enriched_at
      FROM policy_documents WHERE url=ANY($1::text[]) LIMIT 1`, [urls])
    if (policy) {
      detail.record_id = policy.id
      if (policy.enriched_at)
        detail.analysis = parseSourceAnalysis({ kind: 'policy', ai_relevance: policy.ai_relevance,
          reason: policy.ai_relevance_reason || '', summary: policy.summary || '', source_quote: policy.source_quote || '', tags: [] })
    }
  } catch (error) {
    // Saved article analysis remains readable if its live record is unavailable.
    if (!detail.analysis && (error as { code?: string })?.code !== '42P01') throw error
  }
  return detail
}
