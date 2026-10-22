import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Radio, Play, Link2 } from 'lucide-react'
import SourceReader, { SourceAnalysisTitle } from './SourceReader'
import {
  httpUrl,
  sourceKey,
  tedDate,
  TED_TITLE,
  tedEditionDate,
  tedEditionLabel,
  type TedIssue,
  type TedReport,
  type TedSource,
} from '../../lib/ted'

function Copy({ text, topicId }: { text: string; topicId?: string }) {
  const content = topicId
    ? text.replace(/\[(\d+)\](?!\()/g, '[$1](#ref-' + topicId + '-$1)')
    : text
  return (
    <div className="ted-prose">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h4>{children}</h4>,
          h2: ({ children }) => <h4>{children}</h4>,
          h3: ({ children }) => <h4>{children}</h4>,
          a: ({ href, children }) =>
            href?.startsWith('#ref-') ? (
              <a
                className="ted-citation"
                href={href}
                aria-label={`查看引用 ${String(children)}`}
              >
                [{children}]
              </a>
            ) : href && httpUrl(href) ? (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            ) : (
              <span>{children}</span>
            ),
          // Report images use explicit captioned fields instead of arbitrary Markdown embeds.
          img: ({ alt }) => <span>{alt}</span>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}

export function TedPicture({
  image,
  cover = false,
}: {
  image: { url: string; alt: string }
  cover?: boolean
}) {
  return httpUrl(image.url) ? (
    <figure className={cover ? 'ted-picture ted-cover-picture' : 'ted-picture'}>
      {/* Arbitrary editorial image hosts are intentional; no server-side image proxy. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={image.url}
        alt={image.alt}
        loading={cover ? 'eager' : 'lazy'}
        decoding="async"
        referrerPolicy="no-referrer"
      />
      <figcaption>{image.alt}</figcaption>
    </figure>
  ) : null
}

function Source({
  source,
  n,
  topicId,
}: {
  source: TedSource
  n: number
  topicId: string
}) {
  return (
    <li id={`ref-${topicId}-${n}`} className="ted-source">
      <span className="ted-reference-no">[{n}]</span>
      <div>
        <SourceAnalysisTitle className="ted-source-title" sourceId={source.id} title={source.title} />
        <div className="metadata">
          {source.publisher && <span>{source.publisher}</span>}
          {source.url.startsWith('https://mp.weixin.qq.com/') && (
            <span>微信公众号</span>
          )}
          {source.published_at && (
            <span>
              {source.date_basis === 'collected' ? '收录于 ' : ''}
              {tedDate(source.published_at)}
            </span>
          )}
          <a className="ted-source-original" href={source.url} target="_blank" rel="noopener noreferrer">原文</a>
        </div>
        {source.reason && <p className="ted-source-reason">{source.reason}</p>}
      </div>
    </li>
  )
}

export default function TedReportView({
  report,
  issue,
}: {
  report: TedReport
  issue: Pick<TedIssue, 'id' | 'updated_at'>
}) {
  const sources = [...new Map(report.topics.flatMap((topic) => topic.sources).map((source) => [sourceKey(source), source])).values()]
  return (
    <SourceReader issueId={issue.id}>
    <article className="surface ted-report">
      <header className="ted-report-head">
        <div className="ted-masthead">
          <h1>{TED_TITLE}</h1>
          <time className="ted-edition" dateTime={tedEditionDate(report)}>
            {tedEditionLabel(report)}
          </time>
        </div>
        <h2 className="ted-report-title">{report.title || '本期报告'}</h2>
        {report.tags.length > 0 && (
          <div className="ted-tags">
            {report.tags.map((tag) => (
              <span key={tag} className="pill clay">
                {tag}
              </span>
            ))}
          </div>
        )}
        {(report.live_at || report.live_url || report.replay_url) && (
          <div className="ted-broadcast">
            {report.live_at && (
              <span>
                <Radio size={16} />
                直播时间 {tedDate(report.live_at, true)}
              </span>
            )}
            {report.live_url && (
              <a
                className="soft-button"
                href={report.live_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                进入直播
              </a>
            )}
            {report.replay_url && (
              <a
                className="primary-button"
                href={report.replay_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                <Play size={14} />
                观看回放
              </a>
            )}
          </div>
        )}
      </header>
      {report.cover && <TedPicture image={report.cover} cover />}
      {report.intro && (
        <section className="ted-intro" aria-label="本期导读">
          <Copy text={report.intro} />
        </section>
      )}
      {report.topics.length > 0 && (
        <nav className="ted-contents" aria-label="本期目录">
          {report.topics.map((topic, i) => (
            <a key={topic.id} href={`#topic-${topic.id}`}>
              <span>{i + 1}</span>
              {topic.title || '本期议题'}
            </a>
          ))}
          <a href="#references">参考资料</a>
        </nav>
      )}
      <div className="ted-report-body">
        {report.topics.map((topic, i) => (
          <section
            className="ted-topic"
            id={`topic-${topic.id}`}
            key={topic.id}
          >
            <div className="ted-topic-heading">
              <span>{String(i + 1).padStart(2, '0')}</span>
              <h3>{topic.title || '本期议题'}</h3>
            </div>
            <div className="ted-topic-main">
              {topic.claim && (
                <div className="ted-judgment">
                  <span className="ted-field-label">本期判断：</span>
                  <Copy text={topic.claim} topicId={topic.id} />
                </div>
              )}
              {topic.body && <Copy text={topic.body} topicId={topic.id} />}
              {topic.image && <TedPicture image={topic.image} />}
              {topic.uncertainty && (
                <div className="ted-observation">
                  <h4>判断边界</h4>
                  <Copy text={topic.uncertainty} topicId={topic.id} />
                </div>
              )}
              {topic.watch && (
                <div className="ted-observation">
                  <h4>怎么验证</h4>
                  <Copy text={topic.watch} topicId={topic.id} />
                </div>
              )}
            </div>
            {topic.sources.length > 0 && (
              <aside
                className="ted-evidence"
                aria-label={`${topic.title}的原文依据`}
              >
                <h4>
                  <Link2 size={16} />
                  原文与依据
                </h4>
                <ol className="ted-sources">
                  {topic.sources.map((source, n) => (
                    <Source
                      key={sourceKey(source)}
                      source={source}
                      n={n + 1}
                      topicId={topic.id}
                    />
                  ))}
                </ol>
              </aside>
            )}
          </section>
        ))}
        <section className="ted-topic ted-bibliography" id="references">
          <h3>完整参考资料</h3>
          <ul>{sources.map((source) => (
            <li key={sourceKey(source)}>
              <span className="ted-reference-publisher" title={source.publisher}>{source.publisher || '原文'}</span>
              <span aria-hidden="true" className="ted-reference-divider">|</span>
              <SourceAnalysisTitle className="ted-reference-title" sourceId={source.id} title={source.title} />
              <a className="ted-reference-original" href={source.url} target="_blank" rel="noopener noreferrer">原文</a>
            </li>
          ))}</ul>
        </section>
        <footer className="ted-report-footer">
          <p>
            {report.generation && <span>AI 辅助整理 · </span>}
            <span>
              素材 {report.coverage.articles.toLocaleString('zh-CN')} 篇文章 /{' '}
              {report.coverage.policies} 份政策 / {report.coverage.sources}{' '}
              个来源
            </span>
            <span>
              {' '}
              · 数据截至 {tedDate(report.cutoff_at, true)}（北京时间）
            </span>
            <span className="ted-footer-update">
              {' '}
              · 更新 {tedDate(issue.updated_at, true).replace(/^\d{4}\//, '')}
            </span>
          </p>
        </footer>
      </div>
    </article>
    </SourceReader>
  )
}
