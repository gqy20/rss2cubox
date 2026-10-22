import { tedEditionDate, tedEditionLabel, type TedIssue } from './ted'

/** The agent-facing representation follows the same audience view as /ted. */
export function tedReadingSummary(issue: TedIssue) {
  return {
    id: issue.id,
    title: issue.report.title,
    intro: issue.report.intro,
    tags: issue.report.tags,
    edition_date: tedEditionDate(issue.report),
    edition_label: tedEditionLabel(issue.report),
    start_date: issue.report.start_date,
    end_date: issue.report.end_date,
    updated_at: issue.updated_at,
    url: `/ted/${issue.id}`,
    api_url: `/api/ted/${issue.id}`,
  }
}

export function tedReadingDetail(issue: TedIssue) {
  const report = issue.report
  return {
    ...tedReadingSummary(issue),
    report: {
      title: report.title,
      intro: report.intro,
      tags: report.tags,
      start_date: report.start_date,
      end_date: report.end_date,
      cutoff_at: report.cutoff_at,
      coverage: report.coverage,
      topics: report.topics.map((topic) => ({
        id: topic.id,
        title: topic.title,
        claim: topic.claim,
        body: topic.body,
        uncertainty: topic.uncertainty,
        watch: topic.watch,
        image: topic.image,
        sources: topic.sources.map((source) => ({
          id: source.id,
          kind: source.kind,
          title: source.title,
          url: source.url,
          publisher: source.publisher,
          published_at: source.published_at,
          date_basis: source.date_basis,
          reason: source.reason,
          analysis_url: `/api/ted/${issue.id}/source?id=${encodeURIComponent(source.id)}`,
        })),
      })),
      cover: report.cover,
      live_at: report.live_at,
      live_url: report.live_url,
      replay_url: report.replay_url,
      generation: report.generation ?? null,
    },
  }
}
