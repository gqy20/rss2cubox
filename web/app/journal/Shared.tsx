import { ScoreIndicator } from './Numbers'
import Link from 'next/link'
import { ArrowRight, FileText, Inbox, AlertCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Row } from '../types'
import type { Policy } from '../../lib/journal-types'
import { dateLabel, safeUrl } from '../../lib/journal-utils'
import { BookmarkButton } from './Actions'
import { articleTeaser } from '../../lib/topic-utils'
import {
  articleDestination,
  policyDestination,
  type ReadingContext,
} from '../../lib/reading-context'
export function PageHeading({
  title,
  children,
}: {
  title: string
  children?: ReactNode
}) {
  return (
    <div className="page-heading">
      <div className="page-heading-main">
        <div className="title-row">
          <h1>{title}</h1>
          {children && <div className="heading-actions">{children}</div>}
        </div>
      </div>
    </div>
  )
}
export function PanelHeading({
  title,
  href,
  action = '查看全部',
  icon,
}: {
  title: string
  href?: string
  action?: string
  icon?: ReactNode
}) {
  return (
    <div className="panel-heading">
      <h2>
        {icon && <span className="section-icon">{icon}</span>}
        {title}
      </h2>
      {href && (
        <Link className="text-link" href={href}>
          {action}
          <ArrowRight size={14} />
        </Link>
      )}
    </div>
  )
}
export function Empty({
  title,
  description,
}: {
  title: string
  description?: string
}) {
  return (
    <div className="empty-state">
      <Inbox size={25} strokeWidth={1.4} />
      <h3>{title}</h3>
      {description && <p>{description}</p>}
    </div>
  )
}
export function DataNotice({ issues }: { issues: string[] }) {
  return issues.length ? (
    <div className="data-notice" role="status">
      <AlertCircle size={17} />
      <span>
        {issues.join('、')}暂时不可用。已展示其余可用数据，可刷新重试。
      </span>
    </div>
  ) : null
}
export function ExternalLink({
  url,
  children,
  className = 'source-link',
}: {
  url?: string | null
  children: ReactNode
  className?: string
}) {
  const href = safeUrl(url)
  return href ? (
    <a
      className={className}
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title="在新标签页阅读原文"
    >
      {children}
      <span className="sr-only">（新标签页打开原文）</span>
    </a>
  ) : (
    <span>{children}</span>
  )
}
export function ArticleRows({
  rows,
  context,
}: {
  rows: Row[]
  context?: ReadingContext
}) {
  return rows.length ? (
    <div className="reading-list">
      {rows.map((row) => (
        <article className="reading-row" key={row.id}>
          <span className="document-symbol">
            <FileText size={18} strokeWidth={1.5} />
          </span>
          <div className="reading-copy">
            <Link
              href={articleDestination(row.id, context)}
              className="reading-title"
            >
              {row.title || '未命名文章'}
            </Link>
            {articleTeaser(row.title, row.core_event || row.hidden_signal) && (
              <p>
                {articleTeaser(row.title, row.core_event || row.hidden_signal)}
              </p>
            )}
            <div className="metadata">
              <span>{row.source}</span>
              <span>{dateLabel(row.time)}</span>
              {row.importance_score != null && (
                <ScoreIndicator label="重要性" value={row.importance_score} />
              )}
            </div>
          </div>
          <BookmarkButton id={row.id} />
        </article>
      ))}
    </div>
  ) : (
    <Empty
      title="还没有可展示的文章"
      description="采集并完成分析后，重点文章会出现在这里。"
    />
  )
}
export function PolicyRows({
  rows,
  context,
  matchTerms,
}: {
  rows: Policy[]
  context?: ReadingContext
  matchTerms?: string[]
}) {
  return rows.length ? (
    <div className="policy-teasers">
      {rows.map((policy) => (
        <article className="policy-teaser" key={policy.id}>
          <span className="document-symbol olive">
            <FileText size={19} strokeWidth={1.5} />
          </span>
          <div>
            <Link href={policyDestination(policy.id, context)}>
              {policy.title}
            </Link>
            {matchTerms && (
              <p className="policy-match-reason">
                匹配词：
                {matchTerms
                  .filter((term) =>
                    `${policy.title} ${policy.summary || ''}`
                      .toLowerCase()
                      .includes(term.toLowerCase()),
                  )
                  .join('、') || '未记录具体命中词'}
              </p>
            )}
            <div className="metadata">
              <span>{policy.region || '地区未明确'}</span>
              <span>{dateLabel(policy.published_at)}</span>
            </div>
          </div>
        </article>
      ))}
    </div>
  ) : (
    <Empty
      title="还没有已分析的相关政策"
      description="已收录文件可在政策库中查看。"
    />
  )
}
export function JsonEvidence({ value }: { value: unknown }) {
  if (value == null || value === '') return <p className="muted-text">未记录</p>
  if (Array.isArray(value))
    return value.length ? (
      <ul className="evidence-list">
        {value.map((v, i) => (
          <li key={i}>
            <JsonEvidence value={v} />
          </li>
        ))}
      </ul>
    ) : (
      <p className="muted-text">未记录</p>
    )
  if (typeof value === 'object') {
    const entries = Object.entries(value)
    const labels: Record<string, string> = {
      description: '说明',
      metric: '指标',
      threshold: '阈值',
      evidence: '证据',
      conditions: '条件',
      sources: '来源',
      required: '要求',
      title: '标题',
      text: '内容',
      type: '类型',
    }
    return entries.length ? (
      <dl className="evidence-fields">
        {entries.map(([k, v]) => (
          <div key={k}>
            <dt>{labels[k] || k}</dt>
            <dd>
              <JsonEvidence value={v} />
            </dd>
          </div>
        ))}
      </dl>
    ) : (
      <p className="muted-text">未记录</p>
    )
  }
  const text = String(value)
  return safeUrl(text) ? (
    <ExternalLink url={text}>{text}</ExternalLink>
  ) : (
    <span>{text}</span>
  )
}
