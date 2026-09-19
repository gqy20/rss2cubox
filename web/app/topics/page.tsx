import Link from 'next/link'
import { BookOpen, Files, ArrowRight } from 'lucide-react'
import {
  getJournal,
  topicArticles,
  relatedPolicies,
} from '../../lib/journal-store'
import { clusterStatus, dateLabel } from '../../lib/journal-utils'
import {
  PageHeading,
  DataNotice,
  Empty,
  ArticleRows,
  PolicyRows,
} from '../journal/Shared'
export const dynamic = 'force-dynamic'
export default async function TopicsPage({
  searchParams,
}: {
  searchParams: Promise<{ id?: string }>
}) {
  const { id } = await searchParams,
    data = await getJournal()
  const selected =
    data.clusters.find((c) => String(c.id) === id) || data.clusters[0]
  if (!selected)
    return (
      <>
        <PageHeading
          title="专题对读"
          description="从同一个问题出发，分别核对技术证据与政策文件。"
        />
        <DataNotice issues={data.issues.filter((i) => i === '专题')} />
        <section className="surface">
          <Empty
            title="还没有信号专题"
            description="运行聚类后，跨文章的主题会出现在这里。"
          />
        </section>
      </>
    )
  const terms = [
    ...(selected.entities || []),
    ...(selected.watch_keywords || []),
  ]
  const [articles, policies] = await Promise.allSettled([
    topicArticles(selected.id),
    relatedPolicies(terms),
  ])
  return (
    <>
      <PageHeading
        title="专题对读"
        description="材料相互参照，结论仍需分别核验。"
      />
      <DataNotice
        issues={[
          ...(articles.status === 'rejected' ? ['专题文章'] : []),
          ...(policies.status === 'rejected' ? ['相关政策'] : []),
        ]}
      />
      <nav className="topic-tabs" aria-label="选择专题">
        {data.clusters.map((c) => (
          <Link
            className="topic-tab"
            aria-current={c.id === selected.id ? 'page' : undefined}
            key={c.id}
            href={`/topics?id=${c.id}`}
          >
            <span>{c.label}</span>
            <small>
              {c.article_count} 篇文章 · {c.source_count} 个来源
            </small>
          </Link>
        ))}
      </nav>
      <article className="surface">
        <header className="topic-header">
          <span className="pill clay">
            {clusterStatus[selected.status] || selected.status}
          </span>
          <h2>{selected.label}</h2>
          <p>
            {selected.summary ||
              '根据多来源文章归纳的主题。请结合原文判断关联是否成立。'}
          </p>
          <div className="metadata" style={{ marginTop: 15 }}>
            AI 聚类
            <span>
              {selected.article_count} 篇文章 · {selected.source_count} 个来源
            </span>
            <span>更新于 {dateLabel(selected.updated_at, true)}</span>
          </div>
        </header>
        <div className="comparison">
          <section>
            <h3>
              <BookOpen size={19} />
              技术侧 · 看文章与证据
            </h3>
            <ArticleRows
              rows={articles.status === 'fulfilled' ? articles.value : []}
            />
          </section>
          <section className="policy-side">
            <h3>
              <Files size={19} />
              政策侧 · 看文件与适用范围
            </h3>
            <p className="association-note">
              按专题实体与关键词检索的候选关联，尚未确认适用关系。
            </p>
            <PolicyRows
              rows={policies.status === 'fulfilled' ? policies.value : []}
            />
            {terms.length > 0 && (
              <p className="snapshot-note">
                匹配词：{terms.slice(0, 6).join('、')}
              </p>
            )}
            <Link
              className="text-link"
              style={{ marginTop: 24 }}
              href="/policies"
            >
              继续查找政策
              <ArrowRight size={15} />
            </Link>
          </section>
        </div>
      </article>
      {data.predictions.some((p) => p.signal_cluster_id === selected.id) && (
        <section className="surface" style={{ marginTop: 22 }}>
          <h2>这个专题的待验证判断</h2>
          {data.predictions
            .filter((p) => p.signal_cluster_id === selected.id)
            .map((p) => (
              <div className="reading-row" key={p.id}>
                <Link
                  className="reading-title"
                  href={`/predictions?id=${p.id}`}
                >
                  {p.prediction_title}
                  <span className="metadata">
                    验证窗口至 {dateLabel(p.target_end_at)}
                  </span>
                </Link>
              </div>
            ))}
        </section>
      )}
    </>
  )
}
