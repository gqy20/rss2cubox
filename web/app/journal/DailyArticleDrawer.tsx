'use client'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { X, ExternalLink, Maximize2 } from 'lucide-react'
import Link from 'next/link'
import MarkdownRenderer from '../MarkdownRenderer'

type Article = {
  id: string
  title: string
  url: string
  source_feed_name?: string | null
  source?: string | null
  importance_score?: number | null
  reason?: string | null
  hidden_signal?: string | null
  actionable?: string | null
  prediction?: string | null
  tags?: string[]
  full_text?: string | null
  description?: string | null
}

/**
 * 日报页右侧滑出的文章分析面板。
 * 设计：不跳页（读完继续读日报，Esc/点遮罩关闭），轻量分析视图
 * （重要性/为何重要/隐含信号/可行动/预测/正文）；「在阅读器中打开」
 * 给需要完整功能（收藏/导出）的场景留 /signals 全功能入口。
 */
export default function DailyArticleDrawer({
  articleId,
  onClose,
}: {
  articleId: string | null
  onClose: () => void
}) {
  const [data, setData] = useState<Article | null>(null)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'summary' | 'original'>('summary')
  const alive = useRef(false)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  useEffect(() => {
    if (!articleId) return
    setData(null)
    setError('')
    setTab('summary')
    const controller = new AbortController()
    fetch(`/api/reader/article?id=${encodeURIComponent(articleId)}`, {
      signal: controller.signal,
    })
      .then(async (r) => {
        const body = await r.json()
        if (!r.ok) throw new Error(body.error)
        return body.data as Article
      })
      .then((d) => {
        if (alive.current) setData(d)
      })
      .catch((e) => {
        if (!controller.signal.aborted && alive.current)
          setError(e.message || '加载失败')
      })
    return () => controller.abort()
  }, [articleId])
  useEffect(() => {
    if (!articleId) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [articleId, onClose])
  if (!articleId) return null
  const source = data?.source || data?.source_feed_name
  return createPortal(
    <>
      <button
        className="drawer-backdrop"
        aria-label="关闭详情"
        onClick={onClose}
      />
      <aside className="drawer-panel" role="dialog" aria-label="文章分析">
        <header className="drawer-head">
          <div className="drawer-head-main">
            <h2>{data?.title || (error ? '详情不可用' : '正在加载…')}</h2>
            {source && <span className="drawer-source">{source}</span>}
          </div>
          <div className="drawer-head-actions">
            {data && (
              <Link
                className="icon-button"
                href={`/signals?id=${data.id}`}
                aria-label="在阅读器中打开"
                title="在阅读器中打开（完整功能）"
              >
                <Maximize2 size={15} />
              </Link>
            )}
            {data?.url && (
              <a
                className="icon-button"
                href={data.url}
                target="_blank"
                rel="noreferrer"
                aria-label="打开原文"
                title="打开原文"
              >
                <ExternalLink size={16} />
              </a>
            )}
            <button className="icon-button" aria-label="关闭" onClick={onClose}>
              <X size={17} />
            </button>
          </div>
        </header>
        {data && (
          <div className="drawer-tabs" role="group">
            <button
              aria-pressed={tab === 'summary'}
              onClick={() => setTab('summary')}
            >
              概览与分析
            </button>
            <button
              aria-pressed={tab === 'original'}
              onClick={() => setTab('original')}
            >
              正文
            </button>
          </div>
        )}
        <div className="drawer-body">
          {error ? (
            <p className="drawer-error">{error}</p>
          ) : !data ? (
            <>
              <div className="loading-skeleton" />
              <div className="loading-skeleton" />
            </>
          ) : tab === 'summary' ? (
            <>
              {data.reason && (
                <section>
                  <h3>
                    为何重要
                    {typeof data.importance_score === 'number' && (
                      <span className="drawer-meta-inline">
                        重要性 <b>{data.importance_score}</b> / 5
                      </span>
                    )}
                  </h3>
                  <p>{data.reason}</p>
                </section>
              )}
              {typeof data.importance_score === 'number' && !data.reason && (
                <p className="drawer-meta">
                  重要性 <b>{data.importance_score}</b> / 5
                </p>
              )}
              {data.hidden_signal && (
                <section>
                  <h3>隐含信号</h3>
                  <p>{data.hidden_signal}</p>
                </section>
              )}
              {data.actionable && (
                <section>
                  <h3>可行动</h3>
                  <p>{data.actionable}</p>
                </section>
              )}
              {data.prediction && (
                <section>
                  <h3>趋势预测</h3>
                  <p>{data.prediction}</p>
                </section>
              )}
              {!!data.tags?.length && (
                <p className="drawer-tags">
                  {data.tags.slice(0, 10).map((t) => (
                    <span key={t} className="pill neutral">
                      {t}
                    </span>
                  ))}
                </p>
              )}
            </>
          ) : (
            <div className="prose drawer-fulltext">
              <MarkdownRenderer>
                {(data.full_text || data.description || '暂无已抓取正文。').slice(
                  0,
                  12000,
                )}
              </MarkdownRenderer>
            </div>
          )}
        </div>
      </aside>
    </>,
    document.body,
  )
}
