'use client'
import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, ArrowRight, RefreshCw, X } from 'lucide-react'
import type { Row } from '../types'
import type { Policy, PageResult } from '../../lib/journal-types'
import { dateLabel, excerpt } from '../../lib/journal-utils'
import { Empty, ExternalLink } from './Shared'
import { BookmarkButton, ExportButton } from './Actions'
import MarkdownRenderer from '../MarkdownRenderer'

type Filters = {
  search: string
  mode: string
  date: string
  source: string
  tag: string
  region: string
  stage: string
  instrument_type: string
}
const emptyFilters: Filters = {
  search: '',
  mode: 'all',
  date: '',
  source: '',
  tag: '',
  region: '',
  stage: '',
  instrument_type: '',
}
type Props = {
  kind: 'signals' | 'policies'
  initial: Partial<Filters>
  initialId?: string
  sources?: string[]
  facets?: { region: string[]; stage: string[]; instrument_type: string[] }
}
export default function Reader({
  kind,
  initial,
  initialId,
  sources = [],
  facets,
}: Props) {
  const [filters, setFilters] = useState<Filters>({
    ...emptyFilters,
    ...initial,
  })
  const [page, setPage] = useState(1),
    [version, setVersion] = useState(0)
  const [result, setResult] = useState<PageResult<Row | Policy> | null>(null)
  const [loading, setLoading] = useState(true),
    [error, setError] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(initialId || null)
  const [detail, setDetail] = useState<Row | Policy | null>(null),
    [detailLoading, setDetailLoading] = useState(false),
    [detailError, setDetailError] = useState('')
  const [tab, setTab] = useState('summary')
  const encoded = new URLSearchParams({
    ...filters,
    page: String(page),
  }).toString()
  const change = (key: keyof Filters, value: string) => {
    setFilters((f) => ({ ...f, [key]: value }))
    setPage(1)
    setSelectedId(null)
  }
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/reader/${kind}?${encoded}`, {
          signal: controller.signal,
        })
        const payload = await response.json()
        if (!response.ok) throw new Error(payload.error || '加载失败')
        if (controller.signal.aborted) return
        setResult(payload)
        if (window.matchMedia('(min-width: 901px)').matches)
          setSelectedId((prev) => prev || payload.data[0]?.id || null)
      } catch (e) {
        if (!controller.signal.aborted) {
          setError(e instanceof Error ? e.message : '加载失败')
          setResult(null)
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }, 250)
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [kind, encoded, version])
  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      setDetailError('')
      setDetailLoading(false)
      return
    }
    const controller = new AbortController()
    setDetail(null)
    setDetailLoading(true)
    setDetailError('')
    setTab('summary')
    fetch(
      `/api/reader/${kind === 'signals' ? 'article' : 'policy'}?id=${encodeURIComponent(selectedId)}`,
      { signal: controller.signal },
    )
      .then(async (r) => {
        const body = await r.json()
        if (!r.ok) throw new Error(body.error)
        return body.data
      })
      .then((data) => {
        if (!controller.signal.aborted) setDetail(data)
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setDetailError(e.message || '详情加载失败')
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false)
      })
    return () => controller.abort()
  }, [selectedId, kind, version])
  const policy = kind === 'policies',
    article = detail as Row | null,
    document = detail as Policy | null
  return (
    <>
      <div className="toolbar">
        <input
          aria-label={policy ? '搜索政策' : '搜索信号'}
          type="search"
          placeholder={
            policy
              ? '搜索政策、发布机构或适用主体…'
              : '搜索标题、摘要、标签或正文…'
          }
          value={filters.search}
          onChange={(e) => change('search', e.target.value)}
        />
        {policy ? (
          <>
            {(['region', 'stage', 'instrument_type'] as const).map((key, i) => (
              <label key={key}>
                {['地区', '阶段', '文件类型'][i]}
                <select
                  value={filters[key]}
                  onChange={(e) => change(key, e.target.value)}
                >
                  <option value="">全部</option>
                  {facets?.[key].map((v) => (
                    <option key={v}>{v}</option>
                  ))}
                </select>
              </label>
            ))}
          </>
        ) : (
          <>
            <label>
              来源
              <select
                value={filters.source}
                onChange={(e) => change('source', e.target.value)}
              >
                <option value="">全部来源</option>
                {sources.map((source) => (
                  <option key={source}>{source}</option>
                ))}
              </select>
            </label>
            <label>
              日期
              <input
                type="date"
                value={filters.date}
                onChange={(e) => change('date', e.target.value)}
              />
            </label>
            {filters.tag && (
              <button className="soft-button" onClick={() => change('tag', '')}>
                {filters.tag}
                <X size={13} />
              </button>
            )}
          </>
        )}
        <button
          className="soft-button"
          onClick={() => {
            setFilters(emptyFilters)
            setPage(1)
            setSelectedId(null)
          }}
        >
          重置
        </button>
      </div>
      <div className="toolbar">
        <div className="segments" role="tablist" aria-label="内容筛选">
          {(policy
            ? [
                ['all', '全部文件'],
                ['relevant', '高相关政策'],
                ['analyzed', '已分析'],
              ]
            : [
                ['all', '全部信号'],
                ['high', '重点文章'],
                ['analyzed', '已有分析'],
              ]
          ).map(([value, label]) => (
            <button
              key={value}
              role="tab"
              aria-selected={filters.mode === value}
              onClick={() => change('mode', value)}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="muted-text" aria-live="polite">
          {loading
            ? '正在查找…'
            : result
              ? `${result.total.toLocaleString()} ${policy ? '份文件' : '篇文章'}`
              : ''}
        </span>
        <button
          className="soft-button"
          disabled={loading}
          onClick={() => setVersion((v) => v + 1)}
        >
          <RefreshCw size={14} />
          刷新列表
        </button>
      </div>
      <div className={`reader-grid ${selectedId ? 'has-selection' : ''}`}>
        <section
          className="surface reader-list"
          aria-label={policy ? '政策列表' : '文章列表'}
          aria-busy={loading}
        >
          {loading ? (
            <>
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="loading-skeleton" />
              ))}
            </>
          ) : error ? (
            <div className="empty-state" role="alert">
              <p>{error}</p>
              <button
                className="soft-button"
                onClick={() => setVersion((v) => v + 1)}
              >
                重试
              </button>
            </div>
          ) : result?.data.length ? (
            <>
              {result.data.map((item) => {
                const p = item as Policy,
                  r = item as Row
                return (
                  <button
                    className="reader-item"
                    key={item.id}
                    aria-pressed={selectedId === item.id}
                    onClick={() => setSelectedId(item.id)}
                  >
                    <span className="metadata">
                      {policy
                        ? p.region || p.site_name || '政策文件'
                        : r.source}
                      <span>{dateLabel(policy ? p.published_at : r.time)}</span>
                    </span>
                    <h3>{item.title}</h3>
                    <p>
                      {excerpt(
                        policy ? p.summary : r.core_event || r.hidden_signal,
                        90,
                      ) ||
                        (policy
                          ? '尚未生成政策分析，可查看原文。'
                          : '打开阅读详情。')}
                    </p>
                    {policy && (
                      <span className="metadata">
                        {p.enriched_at ? p.stage || '阶段未明确' : '待分析'}
                      </span>
                    )}
                  </button>
                )
              })}
              <div className="pagination">
                <button
                  className="soft-button"
                  disabled={page === 1}
                  onClick={() => {
                    setPage((p) => p - 1)
                    setSelectedId(null)
                  }}
                >
                  上一页
                </button>
                <span>
                  {page} / {Math.ceil(result.total / 30) || 1}
                </span>
                <button
                  className="soft-button"
                  disabled={!result.hasMore}
                  onClick={() => {
                    setPage((p) => p + 1)
                    setSelectedId(null)
                  }}
                >
                  下一页
                </button>
              </div>
            </>
          ) : (
            <Empty
              title="没有匹配的内容"
              description="尝试减少筛选条件，或换一个关键词。"
            />
          )}
        </section>
        <section
          className="surface reader-document"
          aria-label="阅读详情"
          aria-busy={detailLoading}
        >
          <div className="document-topline">
            <button
              className="soft-button mobile-back"
              onClick={() => setSelectedId(null)}
            >
              <ArrowLeft size={14} />
              返回列表
            </button>
            {detail && (
              <>
                <ExternalLink url={detail.url} />
                <div>
                  <BookmarkButton
                    id={detail.id}
                    kind={policy ? 'policy' : 'article'}
                  />
                  <ExportButton
                    data={detail}
                    name={policy ? 'policy' : 'article'}
                  />
                </div>
              </>
            )}
          </div>
          {detailLoading ? (
            <>
              {[1, 2, 3].map((i) => (
                <div key={i} className="loading-skeleton" />
              ))}
            </>
          ) : detailError ? (
            <div role="alert">
              <Empty title="详情暂时不可用" description={detailError} />
              <button
                className="soft-button"
                onClick={() => setVersion((v) => v + 1)}
              >
                重试
              </button>
            </div>
          ) : detail ? (
            <>
              <h2>{detail.title}</h2>
              <div className="metadata">
                {policy
                  ? document?.issuing_authority || document?.site_name
                  : article?.source}
                <span>
                  {dateLabel(
                    policy ? document?.published_at : article?.time,
                    true,
                  )}
                </span>
              </div>
              {policy && document ? (
                <>
                  <div className="facts">
                    <span>
                      阶段 <b>{document.stage || '未明确'}</b>
                    </span>
                    <span>
                      生效日期 <b>{document.effective_date || '原文未明确'}</b>
                    </span>
                  </div>
                  <div className="document-section">
                    <h3>
                      政策摘要 <span className="ai-label">AI 提炼</span>
                    </h3>
                    <p>
                      {document.summary ||
                        '这份文件还没有完成分析，请先查看原文。'}
                    </p>
                  </div>
                  {document.affected_parties?.length > 0 && (
                    <div className="document-section">
                      <h3>可能适用的主体</h3>
                      <p>{document.affected_parties.join('、')}</p>
                    </div>
                  )}
                  {document.source_quote && (
                    <div className="quote-box">
                      <small>提取的原文引句 · 请与原文核对</small>
                      {document.source_quote}
                    </div>
                  )}
                  <div className="document-section">
                    <Link
                      className="primary-button"
                      href={`/policies/${encodeURIComponent(detail.id)}`}
                    >
                      阅读条款与完整解读
                      <ArrowRight size={15} />
                    </Link>
                  </div>
                </>
              ) : (
                article && (
                  <>
                    <div
                      className="document-tabs"
                      role="tablist"
                      aria-label="阅读内容"
                    >
                      <button
                        role="tab"
                        aria-selected={tab === 'summary'}
                        onClick={() => setTab('summary')}
                      >
                        概览与分析
                      </button>
                      <button
                        role="tab"
                        aria-selected={tab === 'original'}
                        onClick={() => setTab('original')}
                      >
                        已抓取正文
                      </button>
                    </div>
                    {tab === 'original' ? (
                      article.full_text ? (
                        <div className="prose">
                          <MarkdownRenderer>
                            {article.full_text}
                          </MarkdownRenderer>
                        </div>
                      ) : (
                        <Empty
                          title="尚未抓取全文"
                          description="可通过上方“打开原文”阅读来源页面。"
                        />
                      )
                    ) : (
                      <>
                        <div className="facts">
                          {[
                            ['重要性', article.importance_score],
                            ['证据强度', article.evidence_strength],
                            ['置信度', article.confidence],
                          ].map(
                            ([label, value]) =>
                              value != null && (
                                <span key={label as string}>
                                  {label}
                                  <b>{value}/5</b>
                                </span>
                              ),
                          )}
                        </div>
                        {[
                          ['内容摘要', article.core_event],
                          ['隐藏信号', article.hidden_signal],
                          ['判断依据', article.reason],
                          ['行动建议', article.actionable],
                          ['后续预测', article.prediction],
                        ].map(
                          ([label, text]) =>
                            text && (
                              <div className="document-section" key={label}>
                                <h3>
                                  {label}{' '}
                                  {label !== '内容摘要' && (
                                    <span className="ai-label">AI 分析</span>
                                  )}
                                </h3>
                                <div className="prose">
                                  <MarkdownRenderer>{text}</MarkdownRenderer>
                                </div>
                              </div>
                            ),
                        )}
                        {!article.core_event &&
                          !article.hidden_signal &&
                          !article.reason && (
                            <Empty
                              title="这篇文章还没有分析内容"
                              description="可以先打开原文阅读。"
                            />
                          )}
                        {article.tags?.length ? (
                          <div className="toolbar">
                            {article.tags.map((tag) => (
                              <button
                                className="pill olive"
                                style={{ border: 0 }}
                                key={tag}
                                onClick={() => change('tag', tag)}
                              >
                                {tag}
                              </button>
                            ))}
                          </div>
                        ) : null}
                      </>
                    )}
                  </>
                )
              )}
            </>
          ) : (
            <Empty
              title="选择一条内容，开始阅读"
              description="分析、来源和证据会显示在这里。"
            />
          )}
        </section>
      </div>
    </>
  )
}
