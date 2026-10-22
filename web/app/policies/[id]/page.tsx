import { ScoreIndicator } from '../../journal/Numbers'
import { notFound } from 'next/navigation'
import { FileText } from 'lucide-react'
import { readPolicy } from '../../../lib/journal-store'
import { dateLabel } from '../../../lib/journal-utils'
import { isResourceMaterial } from '../../../lib/policy-utils'
import { ExternalLink, JsonEvidence } from '../../journal/Shared'
import { BookmarkButton, ExportButton } from '../../journal/Actions'
import MarkdownRenderer from '../../MarkdownRenderer'
import {
  ReturnLink,
  WindowReadingPosition,
} from '../../journal/ReadingNavigation'
import PolicyApplicability from '../../journal/PolicyApplicability'
import RememberDisclosure from '../../journal/RememberDisclosure'
export const dynamic = 'force-dynamic'
export default async function PolicyPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>
  searchParams: Promise<{ from?: string }>
}) {
  const { id } = await params,
    policy = await readPolicy(id)
  if (!policy) notFound()
  const { from } = await searchParams
  const resource = isResourceMaterial(policy)
  return (
    <>
      <WindowReadingPosition memoryKey={`policy:${id}`} />
      <ReturnLink from={from} fallback="/policies" />
      <div className="policy-layout">
        <article className="surface policy-document">
          <div className="document-topline">
            <span className="pill olive">
              <FileText size={13} />
              {policy.instrument_type || '政策文件'}
            </span>
          </div>
          <div className="title-row document-title-row">
            <h1>
              <ExternalLink url={policy.url} className="original-title">
                {policy.title}
              </ExternalLink>
            </h1>
            <div className="heading-actions">
              <BookmarkButton id={id} kind="policy" />
              <ExportButton data={policy} name="policy" />
            </div>
          </div>
          <div className="metadata document-metadata">
            {policy.issuing_authority || policy.site_name}
            <span>
              {policy.published_at
                ? `发布于 ${dateLabel(policy.published_at)}`
                : policy.source_updated_at
                  ? `原站更新 ${dateLabel(policy.source_updated_at)}`
                  : `收录于 ${dateLabel(policy.first_seen_at)} · 原站未标注发布日期`}
            </span>
          </div>
          {policy.source_metadata?.['原站阅读路径'] && (
            <p className="snapshot-note">
              原站阅读路径：{policy.source_metadata['原站阅读路径']}
            </p>
          )}
          <PolicyApplicability
            policy={policy}
            evidenceHref={policy.source_quote ? '#policy-evidence' : undefined}
          />
          <div className="document-section">
            <h3>
              先读摘要 <span className="ai-label">AI 提炼</span>
            </h3>
            <div className="prose">
              <MarkdownRenderer>
                {policy.summary || '此文件尚未完成分析。点击标题可阅读原文。'}
              </MarkdownRenderer>
            </div>
          </div>
          {policy.key_provisions?.length > 0 && (
            <div className="document-section">
              <h3>
                {resource ? '关键信息' : '关键条款'} <span className="ai-label">结构化提取</span>
              </h3>
              <JsonEvidence value={policy.key_provisions} />
            </div>
          )}
          {policy.source_quote && (
            <div className="document-section">
              <h3 id="policy-evidence">原文依据</h3>
              <div className="quote-box">
                <small>提取的原文引句，请与来源文件核对</small>
                {policy.source_quote}
              </div>
            </div>
          )}
          {policy.ai_relevance_reason && (
            <div className="document-section">
              <h3>
                与 AI 的关联 <span className="ai-label">AI 分析</span>
              </h3>
              <p>{policy.ai_relevance_reason}</p>
            </div>
          )}
          <RememberDisclosure
            memoryKey={`policy-full:${id}`}
            summary={policy.content_kind ? '查看来源内容快照' : '查看已抓取全文'}
          >
            <div className="prose">
              {policy.content_kind ? (
                <div style={{ whiteSpace: 'pre-wrap' }}>{policy.full_text || '暂无来源内容快照'}</div>
              ) : (
                <MarkdownRenderer>
                  {policy.full_text || '暂无已抓取全文，点击标题可阅读原文。'}
                </MarkdownRenderer>
              )}
            </div>
          </RememberDisclosure>
        </article>
        <aside className="surface">
          <h2>
            {resource ? '材料信息' : '文件信息'}
          </h2>
          <dl className="policy-facts">
            {(resource ? [
              ['来源', policy.site_name],
              ['材料类型', policy.content_kind],
              ['原站记录ID', policy.source_metadata?.['原站记录ID']],
              ['原站更新', policy.source_updated_at ? dateLabel(policy.source_updated_at, true) : '未标注'],
              ['涉及主体', policy.affected_parties?.join('、')],
              ['分析时间', dateLabel(policy.enriched_at, true)],
            ] : [
              ['管辖范围', policy.jurisdiction || policy.region],
              ['文件阶段', policy.stage],
              ['文件类型', policy.instrument_type],
              ['政策主线', policy.policy_lineage],
              ['文件编号', policy.document_number],
              ['生效日期', policy.effective_date || '原文未明确'],
              ['征集截止', policy.comment_deadline || '原文未明确'],
              ['适用主体', policy.affected_parties?.join('、')],
              ['义务强度', policy.obligation_level],
              ['分析时间', dateLabel(policy.enriched_at, true)],
            ]).map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value || '未明确'}</dd>
              </div>
            ))}
          </dl>
          <div className="policy-ratings">
            <ScoreIndicator label="AI相关度" value={policy.ai_relevance} />
            <ScoreIndicator label="分析置信度" value={policy.confidence} />
          </div>
          <p className="snapshot-note">
            {resource ? '目录、需求与披露属于公开信息线索。实际获取及用途以原站许可、申请条件和授权范围为准。' : '阶段、主体与日期来自结构化提取。未明确的字段保持为空，不以推断补齐。'}
          </p>
        </aside>
      </div>
    </>
  )
}
