import Link from 'next/link'
import { notFound } from 'next/navigation'
import { ArrowLeft } from 'lucide-react'
import { readTedAudienceIssue } from '../../../lib/ted-store'
import { Empty } from '../../journal/Shared'
import TedReportView from '../Report'
import { TED_TITLE } from '../../../lib/ted'
export const dynamic = 'force-dynamic'
export const metadata = { title: `${TED_TITLE} · RSS2Cubox` }

export default async function TedIssuePage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  let issue
  try {
    issue = await readTedAudienceIssue(id)
  } catch {
    return (
      <section className="surface">
        <Empty title="报告暂时不可用" description="请稍后刷新重试。" />
        <Link href="/ted" className="text-link">
          返回他山青年 TED
        </Link>
      </section>
    )
  }
  if (!issue) notFound()
  return (
    <div className="ted-page">
      <Link className="breadcrumb ted-back" href="/ted">
        <ArrowLeft size={15} />
        返回他山青年 TED
      </Link>
      <TedReportView report={issue.report} issue={issue} />
    </div>
  )
}
