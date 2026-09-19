import Link from 'next/link'
import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Sparkles,
  Activity,
  Radio,
  Layers3,
  Files,
  Hourglass,
} from 'lucide-react'
import { getJournal } from '../lib/journal-store'
import { dateLabel, excerpt, insightItems, safeUrl } from '../lib/journal-utils'
import {
  ArticleRows,
  PolicyRows,
  PanelHeading,
  DataNotice,
  Empty,
} from './journal/Shared'
import { Coverage, CountLabel } from './journal/Numbers'
export const dynamic = 'force-dynamic'
export default async function Page() {
  const data = await getJournal()
  const lead = data.clusters
    .filter((c) => c.article_count > 0)
    .sort((a, b) => b.source_count - a.source_count)[0]
  const trends = insightItems(data.insights?.trends),
    advice = insightItems(data.insights?.daily_advices),
    weak = insightItems(data.insights?.weak_signals)
  const pending = data.predictions.filter((p) => p.status === 'pending').length
  return (
    <>
      <div className="cover-heading">
        <div>
          <h1>
            把重要的信息，
            <br className="small-only" />
            读得更深一点<span>。</span>
          </h1>
          <p>从一条新信号，到一份文件，再到一个值得追踪的判断。</p>
        </div>
        <div className="cover-stats">
          <Link href="/signals">
            <CountLabel
              icon={<BookOpen size={16} />}
              label="文章"
              value={data.stats?.total ?? '—'}
            />
          </Link>
          <Link href="/policies">
            <CountLabel
              icon={<Files size={16} />}
              label="政策"
              value={data.policyStats?.total ?? '—'}
            />
          </Link>
          <Link href="/predictions">
            <CountLabel
              icon={<Hourglass size={16} />}
              label="待验证"
              value={data.issues.includes('预测') ? '—' : pending}
            />
          </Link>
        </div>
      </div>
      <DataNotice issues={data.issues} />
      <div className="cover-grid">
        <section className="surface lead-story">
          <div className="lead-kicker">
            <span className="pill clay">
              <Sparkles size={13} /> 本期主议题
            </span>
            <span className="muted-text">由信号簇提炼</span>
          </div>
          {lead ? (
            <>
              <h2>
                <Link href={`/topics?id=${lead.id}`}>{lead.label}</Link>
              </h2>
              <p className="lead-summary">
                {excerpt(lead.summary, 190) ||
                  '查看关联文章，从多个来源追踪同一主题的变化。'}
              </p>
              <div className="lead-footer">
                <span className="metadata">
                  {lead.article_count} 篇文章<span>·</span>
                  {lead.source_count} 个来源<span>·</span>AI 聚类
                </span>
                <Link className="text-link" href={`/topics?id=${lead.id}`}>
                  展开专题 <ArrowRight size={17} />
                </Link>
              </div>
            </>
          ) : (
            <Empty
              title="等待新的主议题"
              description="信号聚类完成后，会在这里展示跨文章的主题线索。"
            />
          )}
          <div className="story-divider" />
          <div className="briefing-preview">
            <div className="briefing-caption">
              <BookOpen size={17} />
              <Link href="/briefing">今日趋势</Link>
              <span className="ai-label">AI 分析</span>
            </div>
            {trends[0] ? (
              <details className="insight-detail">
                <summary>
                  {excerpt(trends[0].text, 110)}
                  <span className="text-link">
                    阅读完整判断 <ArrowRight size={14} />
                  </span>
                </summary>
                <p>{trends[0].text}</p>
                <div className="source-links">
                  {trends[0].source_urls?.map(
                    (url, i) =>
                      safeUrl(url) && (
                        <a
                          key={url}
                          href={url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {trends[0].source_titles?.[i] || `来源 ${i + 1}`}
                        </a>
                      ),
                  )}
                </div>
              </details>
            ) : (
              <p className="muted-text">最新洞察尚未生成。</p>
            )}
            <span className="timestamp">
              洞察生成于 {dateLabel(data.insights?.generated_at, true)}
            </span>
          </div>
        </section>
        <div className="cover-aside">
          <section className="surface policy-panel">
            <PanelHeading
              title="政策阅读"
              href="/policies"
              action="进入政策库"
            />
            <p className="panel-intro">最近收录、已分析的高相关文件</p>
            <PolicyRows rows={data.policies.slice(0, 2)} />
            <div className="panel-bottom">
              <span className="olive-note">先读摘要，再核对原文</span>
              <Link
                href="/policies"
                className="round-link"
                aria-label="浏览政策库"
              >
                <ArrowRight size={17} />
              </Link>
            </div>
          </section>
          <section className="prediction-note">
            <div className="prediction-note-title">
              <span className="document-symbol">
                <Layers3 size={18} />
              </span>
              <h2>让判断，接受时间的检验</h2>
            </div>
            <p>
              {data.reviews.length
                ? `已有 ${data.reviews.length} 条复盘记录，回看支持证据与反证。`
                : '预测仍待验证。保留判断依据，也留意与它相反的证据。'}
            </p>
            <Link className="text-link" href="/predictions">
              打开预测账本 <ArrowRight size={15} />
            </Link>
          </section>
        </div>
      </div>
      <div className="reading-grid">
        <section className="surface">
          <PanelHeading
            title="值得继续读"
            href="/signals?mode=high"
            action="全部重点文章"
            icon={<BookOpen size={18} />}
          />
          <ArticleRows rows={data.articles.slice(0, 5)} />
        </section>
        <section className="surface observations">
          <PanelHeading title="阅读之后" icon={<Radio size={18} />} />
          {[
            { label: '行动建议', items: advice, tone: 'clay' },
            { label: '弱信号', items: weak, tone: 'olive' },
          ].map(({ label, items, tone }) => (
            <div className="observation" key={label}>
              <span className={`pill ${tone}`}>{label}</span>
              {items[0] ? (
                <details className="insight-detail">
                  <summary>
                    {excerpt(items[0].text, 100)}
                    <span className="text-link">
                      展开与来源 <ArrowRight size={13} />
                    </span>
                  </summary>
                  <p>{items[0].text}</p>
                  <div className="source-links">
                    {items[0].source_urls?.map(
                      (url, i) =>
                        safeUrl(url) && (
                          <a
                            href={url}
                            key={url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {items[0].source_titles?.[i] || `来源 ${i + 1}`}
                          </a>
                        ),
                    )}
                  </div>
                </details>
              ) : (
                <p className="muted-text">暂无{label}</p>
              )}
            </div>
          ))}
          <span className="timestamp">以上为 AI 提炼，来源可展开核对。</span>
        </section>
      </div>
      <footer className="home-footer">
        <Link href="/monitor">
          <Activity size={15} />
          <Coverage
            label="政策已析"
            value={data.policyStats?.analyzed}
            total={data.policyStats?.total}
            compact
          />
          <ArrowUpRight size={13} />
        </Link>
      </footer>
    </>
  )
}
