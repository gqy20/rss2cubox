import Link from 'next/link'
import { ArrowRight } from 'lucide-react'
import {
  listTedAudienceIssues,
  readTedAudienceIssue,
} from '../../lib/ted-store'
import { Empty } from '../journal/Shared'
import TedReportView from './Report'
import { TED_TITLE, tedEditionDate, tedEditionLabel } from '../../lib/ted'

export const dynamic = 'force-dynamic'
export const metadata = { title: `${TED_TITLE} · RSS2Cubox` }

export default async function TedPage() {
  const issues = await listTedAudienceIssues().catch(() => null)
  const latest = issues?.[0]
  const issue = latest
    ? await readTedAudienceIssue(latest.id).catch(() => null)
    : null
  return (
    <div className="ted-page">
      {issue ? (
        <TedReportView report={issue.report} issue={issue} />
      ) : (
        <>
          <header className="ted-page-heading">
            <h1>{TED_TITLE}</h1>
          </header>
          <section className="surface">
            <Empty
              title={
                issues === null || latest ? '报告暂时不可用' : '本期报告准备中'
              }
              description={
                issues === null || latest
                  ? '请稍后刷新重试。'
                  : '报告整理完成后会在这里展示，包含本期议题和原文依据。'
              }
            />
          </section>
        </>
      )}
      {issues && issues.length > 1 && (
        <section className="surface ted-archive">
          <div className="panel-heading">
            <h2>往期报告</h2>
          </div>
          {issues.slice(1).map((previous) => (
            <Link
              className="ted-archive-row"
              href={`/ted/${previous.id}`}
              key={previous.id}
            >
              <span className="metadata">
                <time dateTime={tedEditionDate(previous.report)}>
                  {tedEditionLabel(previous.report)}
                </time>
              </span>
              <div>
                <h3>{previous.report.title}</h3>
                <p>{previous.report.tags.join(' · ')}</p>
              </div>
              <ArrowRight size={18} />
            </Link>
          ))}
        </section>
      )}
    </div>
  )
}
