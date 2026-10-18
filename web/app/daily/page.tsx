import Link from 'next/link'
import {
  Newspaper,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  TrendingUp,
  Radar,
  Layers3,
  Gauge,
  Compass,
  ExternalLink,
} from 'lucide-react'
import { queryJournal, readDailyReports, type DailyReport } from '../../lib/journal-store'
import { PageHeading, Empty, DataNotice } from '../journal/Shared'
import { safeReturnPath, withOrigin } from '../../lib/reading-context'

export const dynamic = 'force-dynamic'

// 日报条目的通用形态（weak_signals / trends / daily_advices 同构）
type Item = {
  text?: string
  comment?: string
  source_urls?: string[]
  source_titles?: string[]
  url?: string
  title?: string
  importance_score?: number
  source_feed_name?: string
}
type DailyData = {
  summary?: string
  key_topics?: string[]
  top_articles?: Item[]
  trends?: Item[]
  weak_signals?: Item[]
  daily_advices?: Item[]
  cluster_evolution?: Item[]
  prediction_status?: Item[]
  confidence_level?: string
}

export default async function DailyPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string; from?: string }>
}) {
  const { date, from } = await searchParams
  const origin = safeReturnPath(from)
  const all = await readDailyReports().catch(() => null)
  if (!all) {
    return (
      <>
        <PageHeading title="AI 日报">
          <Newspaper size={18} />
        </PageHeading>
        <section className="surface">
          <Empty title="日报暂不可用" description="数据库连接异常，请稍后重试。" />
        </section>
      </>
    )
  }
  const dates = all.map((r) => r.report_date).slice(0, 30)

  if (!date) {
    return (
      <>
        <PageHeading title="AI 日报">
          <span className="metadata">共 {all.length} 期</span>
        </PageHeading>
        {all.length === 0 ? (
          <section className="surface">
            <Empty
              title="还没有日报"
              description="日报由预测闭环按日生成，首个报告产出后自动出现。"
            />
          </section>
        ) : (
          <section className="surface daily-archive">
            {all.map((r) => (
              <Link
                key={r.report_date}
                className="daily-archive-row"
                href={withOrigin(`/daily?date=${r.report_date}`, origin)}
              >
                <time>{r.report_date}</time>
                {r.data?.confidence_level && (
                  <span className={`pill ${confClass(r.data.confidence_level)}`}>
                    {r.data.confidence_level}
                  </span>
                )}
                <span className="daily-archive-summary">
                  {(r.data?.summary || '').slice(0, 90)}
                </span>
                <span className="daily-archive-meta">
                  重点 {r.data?.top_articles?.length ?? 0} · 趋势{' '}
                  {r.data?.trends?.length ?? 0} · 弱信号{' '}
                  {r.data?.weak_signals?.length ?? 0}
                </span>
              </Link>
            ))}
          </section>
        )}
      </>
    )
  }

  // ── 单日视图 ──
  const wanted = dates.includes(date) ? date : dates[0]
  const report = all.find((r) => r.report_date === wanted)!
  const idx = dates.indexOf(wanted)
  const prev = dates[idx + 1]
  const next = dates[idx - 1]
  const d = report.data || {}
  const linkMap = await buildLinkMap(report)

  const sections = ([
    { id: 'weak', icon: <Radar size={17} />, title: '早期弱信号', items: d.weak_signals || [] },
    { id: 'trends', icon: <TrendingUp size={17} />, title: '趋势研判', items: d.trends || [] },
    { id: 'articles', icon: <Sparkles size={17} />, title: '重点文章', items: d.top_articles || [] },
    { id: 'advice', icon: <Compass size={17} />, title: '行动建议', items: d.daily_advices || [] },
    { id: 'evolution', icon: <Layers3 size={17} />, title: '聚类演化', items: d.cluster_evolution || [] },
    { id: 'predictions', icon: <Gauge size={17} />, title: '预测验证', items: d.prediction_status || [] },
  ] as { id: string; icon: React.ReactNode; title: string; items: Item[] }[]).filter(
    (s) => s.items.length > 0,
  )

  return (
    <>
      <PageHeading title="AI 日报">
        <Newspaper size={18} />
      </PageHeading>
      <article className="surface daily-report">
        <header className="daily-head">
          <div className="daily-nav">
            {prev ? (
              <Link href={`/daily?date=${prev}`} aria-label="前一天">
                <ChevronLeft size={18} /> <time>{prev}</time>
              </Link>
            ) : (
              <span className="daily-nav-end">最早一期</span>
            )}
            <time className="daily-date">{wanted}</time>
            {next ? (
              <Link href={`/daily?date=${next}`} aria-label="后一天">
                <time>{next}</time> <ChevronRight size={18} />
              </Link>
            ) : (
              <span className="daily-nav-end">最新一期</span>
            )}
          </div>
          {d.confidence_level && (
            <span className={`pill ${confClass(d.confidence_level)}`}>
              <Gauge size={13} /> 置信度 {d.confidence_level}
            </span>
          )}
          {d.key_topics?.length ? (
            <div className="daily-topics">
              {d.key_topics.map((t) => (
                <span key={t} className="pill clay">
                  {t}
                </span>
              ))}
            </div>
          ) : null}
        </header>

        {d.summary && <p className="daily-summary">{d.summary}</p>}

        {sections.length > 0 && (
          <nav className="daily-index" aria-label="今日概览">
            <h2>今日概览 · {sections.reduce((n, s) => n + s.items.length, 0)} 条</h2>
            {sections.map((s) => (
              <div key={s.id}>
                <a href={`#${s.id}`}>
                  {s.icon} {s.title}
                </a>
                <span>{s.items.length} 条</span>
              </div>
            ))}
          </nav>
        )}

        {sections.map((s) => (
          <section key={s.id} id={s.id} className="daily-section">
            <h2>
              {s.icon} {s.title}
            </h2>
            {s.id === 'articles'
              ? s.items.map((it, i) => (
                  <ArticleItem key={i} item={it} linkMap={linkMap} />
                ))
              : s.items.map((it, i) => (
                  <TextItem key={i} item={it} linkMap={linkMap} />
                ))}
          </section>
        ))}

        <footer className="daily-footer">
          <div className="daily-recent">
            {dates
              .filter((x) => x !== wanted)
              .slice(0, 7)
              .map((x) => (
                <Link key={x} href={`/daily?date=${x}`} className="text-link">
                  {x}
                </Link>
              ))}
            <Link href="/daily" className="text-link">
              全部 {all.length} 期
            </Link>
          </div>
          <p className="daily-disclaimer">
            内容由 AI 从当日信号自动生成，可能存在错误；重要决策请核对各条目的原文出处。
            生成于 {new Date(report.generated_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}
          </p>
        </footer>
      </article>
    </>
  )
}

// ── 条目渲染 ──

function TextItem({ item, linkMap }: { item: Item; linkMap: Map<string, string> }) {
  return (
    <div className="daily-item">
      {item.text && <p className="daily-item-text">{item.text}</p>}
      {item.comment && (
        <blockquote className="daily-item-comment">{item.comment}</blockquote>
      )}
      <Sources urls={item.source_urls} titles={item.source_titles} linkMap={linkMap} />
    </div>
  )
}

function ArticleItem({ item, linkMap }: { item: Item; linkMap: Map<string, string> }) {
  const internal = item.url ? linkMap.get(item.url) : undefined
  return (
    <div className="daily-item">
      <h3 className="daily-article-title">
        {internal ? (
          <Link href={`/signals?id=${internal}`}>{item.title}</Link>
        ) : (
          <a href={item.url} target="_blank" rel="noreferrer">
            {item.title}
          </a>
        )}
        {item.importance_score ? (
          <span className="pill clay">imp {item.importance_score}</span>
        ) : null}
      </h3>
      {item.source_feed_name && (
        <span className="daily-article-source">来源：{item.source_feed_name}</span>
      )}
      {item.comment && (
        <blockquote className="daily-item-comment">{item.comment}</blockquote>
      )}
      <Sources
        urls={item.url && !internal ? [item.url] : []}
        titles={item.url && !internal ? [item.title || '原文'] : []}
        linkMap={linkMap}
      />
    </div>
  )
}

function Sources({
  urls,
  titles,
  linkMap,
}: {
  urls?: string[]
  titles?: string[]
  linkMap: Map<string, string>
}) {
  const list = (urls || []).map((u, i) => ({
    url: u,
    title: titles?.[i] || u,
    internal: linkMap.get(u),
  }))
  if (!list.length) return null
  return (
    <div className="daily-sources">
      {list.map((s, i) => (
        <span key={i}>
          {s.internal ? (
            <Link href={`/signals?id=${s.internal}`}>{trimTitle(s.title)}</Link>
          ) : (
            <a href={s.url} target="_blank" rel="noreferrer">
              {trimTitle(s.title)} <ExternalLink size={11} />
            </a>
          )}
        </span>
      ))}
    </div>
  )
}

// ── 工具 ──

function trimTitle(t: string) {
  return t.length > 42 ? t.slice(0, 42) + '…' : t
}

function confClass(level: string) {
  if (level.includes('高')) return 'olive'
  if (level.includes('低')) return ''
  return 'clay'
}

/** 把当天全部来源 url 反查站内 articles.id：命中则内链深读，否则外链原文 */
async function buildLinkMap(report: DailyReport): Promise<Map<string, string>> {
  const urls = new Set<string>()
  const collect = (items?: readonly unknown[]) =>
    (items || []).forEach((raw) => {
      const it = raw as Item
      if (it.url) urls.add(it.url)
      ;(it.source_urls || []).forEach((u) => urls.add(u))
    })
  ;[
    report.data?.weak_signals,
    report.data?.trends,
    report.data?.top_articles,
    report.data?.daily_advices,
  ].forEach(collect)
  if (!urls.size) return new Map()
  try {
    const rows = await queryJournal<{ url: string; id: string }>(
      'SELECT url, id FROM articles WHERE url = ANY($1::text[])',
      [[...urls]],
    )
    return new Map(rows.map((r) => [r.url, r.id]))
  } catch {
    return new Map()
  }
}
