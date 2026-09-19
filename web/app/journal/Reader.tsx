'use client'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import {
  useReaderFeed,
  rememberReaderScroll,
  readerScroll,
} from '../../hooks/useReaderFeed'
import { readerUrl, activeFilterCount } from '../../lib/reader-search'
import Link from 'next/link'
import {
  ArrowLeft,
  ArrowRight,
  RefreshCw,
  RotateCcw,
  X,
  LoaderCircle,
} from 'lucide-react'
import type { Row } from '../types'
import type { Policy } from '../../lib/journal-types'
import { dateLabel, excerpt } from '../../lib/journal-utils'
import { Empty, ExternalLink } from './Shared'
import { BookmarkButton, ExportButton } from './Actions'
import MarkdownRenderer from '../MarkdownRenderer'
import { ScoreIndicator } from './Numbers'

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
  sources?: string[]
  facets?: { region: string[]; stage: string[]; instrument_type: string[] }
}
export default function Reader({ kind, sources = [], facets }: Props) {
  const searchParams = useSearchParams()
  const urlQuery = searchParams.toString()
  const filters = Object.fromEntries(
    Object.keys(emptyFilters).map((key) => [
      key,
      searchParams.get(key) || emptyFilters[key as keyof Filters],
    ]),
  ) as Filters
  const requestedId = searchParams.get('id')
  const [detailVersion, setDetailVersion] = useState(0)
  const [selection, setSelection] = useState<{
    query: string
    id: string | null
  }>({ query: '', id: null })
  const [rawDetail, setDetail] = useState<Row | Policy | null>(null),
    [detailLoading, setDetailLoading] = useState(false),
    [detailError, setDetailError] = useState('')
  const [tab, setTab] = useState('summary')
  const listRef = useRef<HTMLElement>(null)
  const encoded = new URLSearchParams({
    ...filters,
  }).toString()
  const {
    result,
    loading: searching,
    error,
    loadingMore,
    moreError,
    newContent,
    cacheKey,
    loadMore,
    refresh,
  } = useReaderFeed<Row | Policy>(kind, encoded)
  const sentinelRef = useRef<HTMLDivElement>(null),
    bodyRef = useRef<HTMLDivElement>(null)
  const selectedId =
    requestedId || (selection.query === encoded ? selection.id : null)
  const detail = rawDetail?.id === selectedId ? rawDetail : null
  const updateUrl = (
    changes: Record<string, string | null>,
    reset = true,
    push = true,
  ) => {
    const url = readerUrl(kind, new URLSearchParams(urlQuery), changes, reset)
    window.history[push ? 'pushState' : 'replaceState'](null, '', url)
  }
  const setSelectedId = (id: string | null) => {
    if (listRef.current?.clientHeight)
      rememberReaderScroll(cacheKey, listRef.current.scrollTop)
    if (!id) setSelection({ query: encoded, id: null })
    updateUrl({ id }, false, Boolean(id))
  }
  const change = (key: keyof Filters, value: string) =>
    updateUrl({ [key]: value })
  const firstId = result?.data[0]?.id
  useEffect(() => {
    if (firstId && window.matchMedia('(min-width:901px)').matches)
      setSelection({ query: encoded, id: firstId })
  }, [firstId, encoded])
  useLayoutEffect(() => {
    const list = listRef.current
    if (list?.clientHeight && !searching)
      list.scrollTop = readerScroll(cacheKey)
  }, [cacheKey, searching, selectedId])
  useLayoutEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 })
  }, [selectedId, tab])
  useEffect(() => {
    if (
      searching ||
      moreError ||
      !result?.hasMore ||
      typeof IntersectionObserver === 'undefined'
    )
      return
    const root = listRef.current,
      target = sentinelRef.current
    if (!root || !target) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && root.clientHeight > 0) void loadMore()
      },
      { root, rootMargin: '300px 0px', threshold: 0 },
    )
    observer.observe(target)
    return () => observer.disconnect()
  }, [
    searching,
    moreError,
    result?.hasMore,
    result?.data.length,
    loadingMore,
    loadMore,
    selectedId,
  ])
  const refreshList = () => {
    setSelection({ query: encoded, id: null })
    updateUrl({ id: null, page: null }, false, false)
    refresh()
  }
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
  }, [selectedId, kind, detailVersion])
  const policy = kind === 'policies',
    article = detail as Row | null,
    document = detail as Policy | null
  return (
    <div className="reader-panel">
      <div className="reader-controls">
        <div className="toolbar">
          {policy ? (
            <>
              {(['region', 'stage', 'instrument_type'] as const).map(
                (key, i) => (
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
                ),
              )}
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
                <button
                  className="soft-button"
                  onClick={() => change('tag', '')}
                >
                  {filters.tag}
                  <X size={13} />
                </button>
              )}
            </>
          )}
          <button
            className="icon-button"
            aria-label="重置筛选"
            title="重置筛选"
            onClick={() => {
              updateUrl(
                Object.fromEntries(
                  Object.keys(emptyFilters)
                    .filter((key) => key !== 'search')
                    .map((key) => [key, null]),
                ),
              )
            }}
          >
            <RotateCcw size={17} />
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
          <span className="search-result-summary" role="status">
            {searching ? (
              '搜索中…'
            ) : error ? (
              '搜索失败'
            ) : result ? (
              <>
                {filters.search && (
                  <span className="result-keyword">“{filters.search}”</span>
                )}
                <b>{result.total.toLocaleString()}</b>{' '}
                {policy ? '份政策' : '篇文章'}
                {activeFilterCount(new URLSearchParams(urlQuery)) > 0 && (
                  <span> · 已筛选</span>
                )}
              </>
            ) : (
              ''
            )}
          </span>

          <button
            className="icon-button"
            aria-label="刷新列表"
            title="刷新列表"
            disabled={searching}
            onClick={refreshList}
          >
            <RefreshCw size={17} />
          </button>
        </div>
        {newContent && (
          <button className="new-content-button" onClick={refreshList}>
            <RefreshCw size={14} />
            有新内容，点击更新
          </button>
        )}
      </div>
      <div className={`reader-grid ${selectedId ? 'has-selection' : ''}`}>
        <section
          className="surface reader-list"
          ref={listRef}
          tabIndex={0}
          onScroll={(e) => {
            if (e.currentTarget.clientHeight)
              rememberReaderScroll(cacheKey, e.currentTarget.scrollTop)
          }}
          aria-label={policy ? '政策列表' : '文章列表'}
          aria-busy={searching}
        >
          {searching ? (
            <>
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="loading-skeleton" />
              ))}
            </>
          ) : error ? (
            <div className="empty-state" role="alert">
              <p>{error}</p>
              <button className="soft-button" onClick={refreshList}>
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
                    <h3>
                      <Highlight text={item.title} query={filters.search} />
                    </h3>
                    <p>
                      {filters.search &&
                      item.search_excerpt &&
                      item.search_field !== '标题' ? (
                        <>
                          <span className="match-field">
                            {item.search_field}命中 ·{' '}
                          </span>
                          <Highlight
                            text={item.search_excerpt}
                            query={filters.search}
                          />
                        </>
                      ) : (
                        excerpt(
                          policy ? p.summary : r.core_event || r.hidden_signal,
                          90,
                        ) || (policy ? '尚未生成政策分析。' : '打开阅读详情。')
                      )}
                    </p>
                    {policy && (
                      <span className="metadata">
                        {p.enriched_at ? p.stage || '阶段未明确' : '待分析'}
                      </span>
                    )}
                  </button>
                )
              })}
              <div className="reader-load-tail" ref={sentinelRef}>
                {loadingMore ? (
                  <span role="status">
                    <LoaderCircle size={15} className="spin" />
                    正在加载…
                  </span>
                ) : moreError ? (
                  <div role="alert">
                    <span>{moreError}</span>
                    <button
                      className="soft-button"
                      onClick={() => void loadMore()}
                    >
                      重试
                    </button>
                  </div>
                ) : result.hasMore ? (
                  <button
                    className="load-more-button"
                    onClick={() => void loadMore()}
                  >
                    继续加载
                  </button>
                ) : (
                  <span>
                    已到底 · {result.data.length} {policy ? '份政策' : '篇文章'}
                  </span>
                )}
              </div>
            </>
          ) : (
            <Empty
              title={
                filters.search
                  ? `没有找到“${filters.search}”`
                  : '没有匹配的内容'
              }
              description={
                activeFilterCount(new URLSearchParams(urlQuery)) > 0
                  ? '可重置筛选，保留关键词继续查找。'
                  : `尝试其他关键词，或切换到${policy ? '文章' : '政策'}搜索。`
              }
            />
          )}
        </section>
        <section
          className="surface reader-document"
          aria-label="阅读详情"
          aria-busy={detailLoading}
        >
          <header className="reader-document-header" hidden={!selectedId}>
            <div className="title-row document-title-row">
              <button
                className="icon-button mobile-back"
                aria-label="返回列表"
                title="返回列表"
                onClick={() => setSelectedId(null)}
              >
                <ArrowLeft size={16} />
              </button>
              {detail ? (
                <>
                  <h2 title={detail.title}>
                    <ExternalLink url={detail.url} className="original-title">
                      {detail.title}
                    </ExternalLink>
                  </h2>
                  <div className="heading-actions">
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
              ) : (
                <h2>{detailError ? '详情暂时不可用' : '正在加载…'}</h2>
              )}
            </div>
            {detail && (
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
            )}
            {detail && !policy && (
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
            )}
          </header>
          <div
            className="reader-document-body"
            ref={bodyRef}
            tabIndex={0}
            aria-label="正文"
          >
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
                  onClick={() => setDetailVersion((v) => v + 1)}
                >
                  重试
                </button>
              </div>
            ) : detail ? (
              <>
                {policy && document ? (
                  <>
                    <div className="facts">
                      <span>
                        阶段 <b>{document.stage || '未明确'}</b>
                      </span>
                      <span>
                        生效日期{' '}
                        <b>{document.effective_date || '原文未明确'}</b>
                      </span>
                    </div>
                    <div className="document-section">
                      <h3>
                        政策摘要 <span className="ai-label">AI 提炼</span>
                      </h3>
                      <p>
                        {document.summary ||
                          '这份文件还没有完成分析，点击上方标题可阅读原文。'}
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
                            description="点击上方标题，阅读来源页面。"
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
                                  <ScoreIndicator
                                    key={String(label)}
                                    label={String(label)}
                                    value={
                                      typeof value === 'number' ? value : null
                                    }
                                  />
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
                                description="点击上方标题，先阅读原文。"
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
          </div>
        </section>
      </div>
    </div>
  )
}

function Highlight({ text, query }: { text: string; query: string }) {
  const keyword = query.trim()
  if (!keyword) return <>{text}</>
  const lower = text.toLocaleLowerCase(),
    needle = keyword.toLocaleLowerCase()
  const parts: React.ReactNode[] = []
  let start = 0,
    index = lower.indexOf(needle)
  while (index !== -1) {
    parts.push(
      text.slice(start, index),
      <mark key={index}>{text.slice(index, index + keyword.length)}</mark>,
    )
    start = index + keyword.length
    index = lower.indexOf(needle, start)
  }
  parts.push(text.slice(start))
  return <>{parts}</>
}
