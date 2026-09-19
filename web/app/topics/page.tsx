import Link from 'next/link'
import { notFound } from 'next/navigation'
import { BookOpen, Files, ArrowRight, Clock3 } from 'lucide-react'
import {
  getJournal,
  topicArticles,
  relatedPolicies,
} from '../../lib/journal-store'
import { clusterStatus, dateLabel } from '../../lib/journal-utils'
import {
  orderedTopics,
  excludedTopic,
  topicPolicyTerms,
} from '../../lib/topic-utils'
import {
  PageHeading,
  DataNotice,
  Empty,
  ArticleRows,
  PolicyRows,
} from '../journal/Shared'
import TopicSelector from '../journal/TopicSelector'
import ExpandableText from '../journal/ExpandableText'
import { ReadingRegion, ReturnLink } from '../journal/ReadingNavigation'
import { safeReturnPath, withOrigin } from '../../lib/reading-context'
import TopicPolicySearch from '../journal/TopicPolicySearch'
export const dynamic = 'force-dynamic'
export default async function TopicsPage({
  searchParams,
}: {
  searchParams: Promise<{ id?: string; from?: string }>
}) {
  const { id, from } = await searchParams,
    data = await getJournal(),
    topics = orderedTopics(data.clusters)
  const selected = id
    ? topics.find((c) => String(c.id) === id)
    : topics.find((c) => !excludedTopic(c))
  if (id && !selected && !data.issues.includes('专题')) notFound()
  const origin = safeReturnPath(from)
  const topicPath = withOrigin(
    `/topics${selected ? `?id=${selected.id}` : ''}`,
    origin,
  )
  const context = {
    from: topicPath,
    filters: { topic: String(selected?.id || '') },
  }
  const header = (
    <PageHeading title="专题对读">
      <TopicSelector
        topics={topics}
        selectedId={selected?.id}
        returnTo={origin}
      />
    </PageHeading>
  )
  if (!selected)
    return (
      <>
        {header}
        <DataNotice issues={data.issues.filter((i) => i === '专题')} />
        <section className="surface">
          <Empty
            title="暂无可阅读的专题"
            description="可通过选择器查看已排除专题，或等待新的信号聚类。"
          />
        </section>
      </>
    )
  const terms = topicPolicyTerms(selected)
  const [articleResult, policyResult] = await Promise.allSettled([
    topicArticles(selected.id),
    relatedPolicies(terms),
  ])
  const articles =
      articleResult.status === 'fulfilled' ? articleResult.value : [],
    policies = policyResult.status === 'fulfilled' ? policyResult.value : []
  const pending = data.predictions.filter(
    (p) => p.signal_cluster_id === selected.id && p.status === 'pending',
  )
  return (
    <>
      {header}
      <DataNotice
        issues={[
          ...(articleResult.status === 'rejected' ? ['专题文章'] : []),
          ...(policyResult.status === 'rejected' ? ['相关政策'] : []),
        ]}
      />
      <ReadingRegion
        className="surface topic-reading"
        key={selected.id}
        memoryKey={`topic:${selected.id}`}
        label="专题内容"
      >
        {origin && <ReturnLink from={origin} />}
        <header className="topic-header">
          <div className="topic-heading-row">
            <h2>{selected.label}</h2>
            <span
              className={`pill ${excludedTopic(selected) ? 'neutral' : 'olive'}`}
            >
              {clusterStatus[selected.status] || '待确认'}
            </span>
          </div>
          <div className="metadata">
            <span>AI 聚类</span>
            <span>
              {selected.article_count} 篇文章 · {selected.source_count} 个来源
            </span>
            <span>更新于 {dateLabel(selected.updated_at, true)}</span>
          </div>
          {excludedTopic(selected) && (
            <p className="association-note">
              此专题已被排除，不作为默认阅读推荐。原始记录保留供回看。
            </p>
          )}
          {selected.summary && (
            <ExpandableText
              text={selected.summary}
              memoryKey={`topic-summary:${selected.id}`}
            />
          )}
        </header>
        {!policies.length && (
          <div className="topic-policy-note">
            <Files size={17} />
            <span>
              {policyResult.status === 'rejected'
                ? '政策检索暂时不可用'
                : '暂无匹配政策'}
            </span>
            <TopicPolicySearch terms={terms} from={topicPath} />
          </div>
        )}
        <div
          className={`comparison topic-comparison ${policies.length ? '' : 'without-policy'}`}
        >
          <section>
            <div className="topic-section-heading">
              <h3>
                <BookOpen size={17} />
                关联文章
              </h3>
              <Link
                className="text-link"
                href={withOrigin(`/signals?topic=${selected.id}`, topicPath)}
              >
                查看全部
                <ArrowRight size={14} />
              </Link>
            </div>
            <ArticleRows rows={articles.slice(0, 8)} context={context} />
            {articles.length > 8 && (
              <Link
                className="topic-more"
                href={withOrigin(`/signals?topic=${selected.id}`, topicPath)}
              >
                继续阅读这个专题的文章
                <ArrowRight size={14} />
              </Link>
            )}
          </section>
          {policies.length > 0 && (
            <section className="policy-side">
              <h3>
                <Files size={17} />
                候选政策 <small>{policies.length}</small>
              </h3>
              <p className="association-note">关键词关联，尚未确认适用关系。</p>
              <PolicyRows
                rows={policies}
                context={{ from: topicPath }}
                matchTerms={terms}
              />
              <details className="metric-definition">
                <summary>关联依据</summary>
                <p>
                  匹配词：{terms.join('、')}
                  。按相关度与发布日期选取，最多展示5份文件。
                </p>
              </details>
            </section>
          )}
        </div>
        {pending.length > 0 && (
          <section className="topic-predictions">
            <div className="topic-section-heading">
              <h3>
                <Clock3 size={17} />
                待验证判断 <small>{pending.length}</small>
              </h3>
            </div>
            {pending.map((p) => (
              <Link
                className="topic-prediction"
                key={p.id}
                href={withOrigin(`/predictions?id=${p.id}`, topicPath)}
              >
                <span>
                  {p.prediction_title}
                  <small>验证窗口至 {dateLabel(p.target_end_at)}</small>
                </span>
                <ArrowRight size={14} />
              </Link>
            ))}
          </section>
        )}
      </ReadingRegion>
    </>
  )
}
