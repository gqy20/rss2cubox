'use client'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import dynamic from 'next/dynamic'
import Link from 'next/link'
import {
  Search,
  X,
  ArrowLeft,
  Clock3,
  TriangleAlert,
  Rss,
  Files,
  ChevronRight,
  Check,
} from 'lucide-react'
import type {
  MonitorSnapshot,
  MonitorSource,
  MonitorStatus,
  MonitorDetail,
  SourceRun,
} from '../../lib/monitor-types'
import type { ArticleStats, PolicyStats } from '../../lib/journal-types'
import {
  monitorLabels,
  monitorOrder,
  needsAttention,
  isStale,
  attentionOrder,
  errorCategory,
  successShare,
  compareSourceNames,
} from '../../lib/monitor-utils'
import { dateLabel } from '../../lib/journal-utils'
import {
  Empty,
  ArticleRows,
  PolicyRows,
  DataNotice,
  PanelHeading,
} from './Shared'
import { Coverage } from './Numbers'
import { useReadingPosition } from '../../hooks/useReadingPosition'
import { withOrigin } from '../../lib/reading-context'
const TrendChart = dynamic(() => import('./TrendChart'), {
  ssr: false,
  loading: () => <div className="loading-skeleton" />,
})
const scrollPositions = new Map<string, number>()
type Props = {
  snapshot: MonitorSnapshot
  stats: ArticleStats | null
  policyStats: PolicyStats | null
  trend: { day: string; articles: number; policies: number }[] | null
  /** Page-level actions rendered at the right end of the controls row. */
  actions?: React.ReactNode
}
function elapsed(value: string | null, now: number) {
  if (!value) return '从未记录'
  const hours = Math.max(0, (now - Date.parse(value)) / 3600000)
  return hours < 1
    ? `${Math.floor(hours * 60)}分钟前`
    : hours < 24
      ? `${Math.floor(hours)}小时前`
      : `${Math.floor(hours / 24)}天前`
}
function historyLabel(run: SourceRun) {
  return `${dateLabel(run.at, true)} · ${monitorLabels[run.status]} · ${run.fetched}条 · ${run.attempts}次请求`
}
function Heartbeat({ source }: { source: MonitorSource }) {
  const runs = [
    ...Array(Math.max(0, 12 - source.runs.length)).fill(null),
    ...source.runs.slice(0, 12).reverse(),
  ] as (SourceRun | null)[]
  return (
    <span
      className="heartbeat"
      role="img"
      aria-label={`最近${source.runs.length}轮：${
        source.runs
          .slice()
          .reverse()
          .map((r) => monitorLabels[r.status])
          .join('、') || '暂无记录'
      }`}
    >
      {runs.map((run, i) => (
        <i
          key={run?.id || i}
          className={`heartbeat-cell ${run?.status || 'missing'}`}
          aria-hidden="true"
          title={run ? historyLabel(run) : '无历史记录'}
        >
          {run?.status === 'failed'
            ? '!'
            : run?.status === 'empty'
              ? '−'
              : run?.status === 'skipped'
                ? '·'
                : ''}
        </i>
      ))}
    </span>
  )
}
function Status({
  source,
  now,
  hours,
}: {
  source: MonitorSource
  now: number
  hours: number
}) {
  return (
    <div className="source-condition">
      <span className={`source-status ${source.status}`}>
        {source.status === 'failed'
          ? errorCategory(source.runs[0]?.error)
          : monitorLabels[source.status]}
      </span>
      {source.failureStreak > 1 && source.status === 'failed' && (
        <small>
          连续{source.failureStreak === 12 ? '≥12' : source.failureStreak}轮失败
        </small>
      )}
      {source.emptyStreak >= 3 && (
        <small>
          连续
          {source.emptyStreak >= 12 && source.kind === 'tech'
            ? '≥12'
            : source.emptyStreak}
          轮空结果
        </small>
      )}
      {source.recovered && source.status === 'ok' && (
        <small className="recovered-note">最近一轮已恢复</small>
      )}
      {isStale(source, now, hours) && (
        <small className="stale-note">
          <Clock3 size={11} />超{hours}h未采集
        </small>
      )}
    </div>
  )
}
export default function SourceMonitor({
  snapshot,
  stats,
  policyStats,
  trend,
  actions,
}: Props) {
  const searchParams = useSearchParams(),
    params = new URLSearchParams(searchParams.toString())
  const view = ['all', 'yield', 'stats'].includes(params.get('view') || '')
    ? params.get('view')!
    : 'attention'
  const kind = ['tech', 'policy'].includes(params.get('kind') || '')
    ? params.get('kind')!
    : 'all'
  const status = monitorOrder.includes(params.get('status') as MonitorStatus)
    ? (params.get('status') as MonitorStatus)
    : 'all'
  const q = params.get('q') || '',
    category = params.get('error') || '',
    hours = [24, 48, 168].includes(Number(params.get('hours')))
      ? Number(params.get('hours'))
      : 24
  const [draft, setDraft] = useState(q),
    [small, setSmall] = useState(true)
  const detailTab = ['history', 'signals', 'topics'].includes(
    params.get('detail') || '',
  )
    ? params.get('detail')!
    : view === 'yield'
      ? 'signals'
      : 'history'
  const signalMode = params.get('content') === 'high' ? 'high' : 'latest',
    runId = params.get('run')
  const listRef = useRef<HTMLDivElement>(null),
    detailRef = useRef<HTMLDivElement>(null)
  const now = Date.parse(snapshot.loadedAt)
  const update = (
    changes: Record<string, string | null>,
    keepSelection = false,
  ) => {
    const next = new URLSearchParams(searchParams.toString())
    if (!keepSelection) {
      for (const key of ['source', 'detail', 'content', 'run']) next.delete(key)
    }
    for (const [key, value] of Object.entries(changes)) {
      if (!value || value === 'all') next.delete(key)
      else next.set(key, value)
    }
    // 'all' is a meaningful view, unlike 'all' in a source/type filter.
    if (changes.view === 'all') next.set('view', 'all')
    window.history.replaceState(
      null,
      '',
      `/monitor${next.size ? '?' + next : ''}`,
    )
  }
  useEffect(() => setDraft(q), [q])
  useEffect(() => {
    const media = window.matchMedia('(max-width:1100px)')
    const sync = () => setSmall(media.matches)
    sync()
    media.addEventListener('change', sync)
    return () => media.removeEventListener('change', sync)
  }, [])
  const filtered = useMemo(
    () =>
      snapshot.sources
        .filter(
          (s) =>
            (kind === 'all' || s.kind === kind) &&
            (status === 'all' || s.status === status) &&
            (!category ||
              (s.status === 'failed' &&
                errorCategory(s.runs[0]?.error) === category)) &&
            (!q ||
              `${s.name} ${s.domain} ${s.address}`
                .toLowerCase()
                .includes(q.toLowerCase())) &&
            (view !== 'attention' || needsAttention(s, now, hours)),
        )
        .sort((a, b) =>
          view === 'yield'
            ? b.high - a.high ||
              b.articles - a.articles ||
              compareSourceNames(a, b)
            : attentionOrder(a, now, hours) - attentionOrder(b, now, hours) ||
              b.failureStreak - a.failureStreak ||
              compareSourceNames(a, b),
        ),
    [snapshot.sources, kind, status, category, q, view, now, hours],
  )
  const selected =
    filtered.find((s) => s.id === params.get('source')) ||
    (!small ? filtered[0] : null)
  const attentionCount = useMemo(
    () => snapshot.sources.filter((s) => needsAttention(s, now, hours)).length,
    [snapshot.sources, now, hours],
  )
  const scrollKey = JSON.stringify([view, kind, status, category, q, hours])
  useLayoutEffect(() => {
    if (listRef.current?.clientHeight)
      listRef.current.scrollTop = scrollPositions.get(scrollKey) || 0
  }, [scrollKey, selected?.id, small])
  const [detailState, setDetailState] = useState<{
      id: string
      data: MonitorDetail | null
      loading: boolean
      error: string
    }>({ id: '', data: null, loading: false, error: '' }),
    [retry, setRetry] = useState(0)
  useEffect(() => {
    if (!selected || view === 'stats') return
    const id = selected.id,
      controller = new AbortController()
    setDetailState({ id, data: null, loading: true, error: '' })
    fetch(`/api/monitor/source?id=${encodeURIComponent(id)}`, {
      signal: controller.signal,
      cache: 'no-store',
    })
      .then(async (r) => {
        const b = await r.json()
        if (!r.ok) throw new Error(b.error || '加载失败')
        return b.data
      })
      .then((data) => {
        if (!controller.signal.aborted)
          setDetailState({ id, data, loading: false, error: '' })
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setDetailState({
            id,
            data: null,
            loading: false,
            error: e.message || '加载失败',
          })
      })
    return () => controller.abort()
  }, [selected?.id, snapshot.loadedAt, view === 'stats', retry])
  const detail = detailState.id === selected?.id ? detailState.data : null
  const activeRun =
    selected?.runs.find((r) => r.id === runId) || selected?.runs[0]
  useReadingPosition(
    detailRef,
    `monitor:${selected?.id}:${detailTab}:${signalMode}:${detailTab === 'history' ? activeRun?.id : ''}`,
    Boolean(selected) && (detailTab === 'history' || Boolean(detail)),
  )
  const sourceParams = new URLSearchParams(searchParams.toString())
  if (selected) sourceParams.set('source', selected.id)
  sourceParams.set('detail', detailTab)
  sourceParams.set('content', signalMode)
  const sourceContext = selected
    ? {
        from: `/monitor?${sourceParams}`,
        filters: {
          sourceRef: selected.id,
          mode: signalMode === 'high' ? 'high' : 'all',
        },
      }
    : undefined
  const errorGroups = useMemo(
    () =>
      Object.entries(
        snapshot.sources
          .filter(
            (s) => s.status === 'failed' && (kind === 'all' || s.kind === kind),
          )
          .reduce<Record<string, number>>((acc, s) => {
            const key = errorCategory(s.runs[0]?.error)
            acc[key] = (acc[key] || 0) + 1
            return acc
          }, {}),
      ).sort((a, b) => b[1] - a[1]),
    [snapshot.sources, kind],
  )
  const distributions = useMemo(
    () =>
      (['tech', 'policy'] as const).map((type) => {
        const sources = snapshot.sources.filter((s) => s.kind === type)
        return {
          type,
          total: sources.length,
          counts: monitorOrder
            .map((key) => ({
              key,
              count: sources.filter((s) => s.status === key).length,
            }))
            .filter((s) => s.count),
        }
      }),
    [snapshot.sources],
  )
  const selectSource = (id: string) => {
    if (listRef.current)
      scrollPositions.set(scrollKey, listRef.current.scrollTop)
    update({ source: id, detail: null, content: null, run: null }, true)
  }
  return (
    <div className={`monitor-panel ${selected ? 'has-source' : ''}`}>
      <section
        className="source-distributions"
        aria-label="信源最近一轮状态分布"
      >
        {distributions.map(({ type, total, counts }) => {
          return (
            <div className="source-distribution" key={type}>
              <button
                className="distribution-name"
                onClick={() =>
                  update({ kind: type, status: null, error: null, view: 'all' })
                }
              >
                {type === 'tech' ? <Rss size={15} /> : <Files size={15} />}
                <span>{type === 'tech' ? '科技源' : '政策源'}</span>
                <b>{total}</b>
              </button>
              <div className="distribution-bar">
                {counts.map(({ key, count }) => (
                  <button
                    key={key}
                    style={{ flex: count }}
                    className={`distribution-segment ${key}`}
                    aria-label={`${type === 'tech' ? '科技' : '政策'}${monitorLabels[key]} ${count}个信源`}
                    title={`${monitorLabels[key]} ${count}`}
                    onClick={() =>
                      update({
                        kind: type,
                        status: key,
                        error: null,
                        view: 'all',
                      })
                    }
                  />
                ))}
              </div>
              <div className="distribution-legend">
                {counts.map(({ key, count }) => (
                  <button
                    key={key}
                    onClick={() =>
                      update({
                        kind: type,
                        status: key,
                        error: null,
                        view: 'all',
                      })
                    }
                  >
                    <i className={`legend-dot ${key}`} />
                    {monitorLabels[key]}
                    <b>{count}</b>
                  </button>
                ))}
              </div>
            </div>
          )
        })}
      </section>
      <div className="source-controls">
        <div className="segments" role="group" aria-label="监控视图">
          {[
            ['attention', '需要关注'],
            ['all', '全部信源'],
            ['yield', '内容产出'],
            ['stats', '统计'],
          ].map(([key, label]) => (
            <button
              key={key}
              aria-pressed={view === key}
              onClick={() => update({ view: key, status: null, error: null })}
            >
              {label}
              {key === 'attention' && <small>{attentionCount}</small>}
            </button>
          ))}
        </div>
        {view !== 'stats' && (
          <>
            <form
              className="source-search"
              role="search"
              onSubmit={(e) => {
                e.preventDefault()
                update({ q: draft.trim() })
              }}
            >
              <Search size={15} />
              <input
                aria-label="搜索信源"
                placeholder="搜索名称、域名…"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
              />
              {draft && (
                <button
                  type="button"
                  aria-label="清空信源搜索"
                  onClick={() => {
                    setDraft('')
                    update({ q: null })
                  }}
                >
                  <X size={14} />
                </button>
              )}
              <button type="submit" aria-label="查找信源">
                <ChevronRight size={16} />
              </button>
            </form>
            <label className="source-filter">
              <span className="sr-only">信源类型</span>
              <select
                aria-label="信源类型"
                value={kind}
                onChange={(e) =>
                  update({ kind: e.target.value, status: null, error: null })
                }
              >
                <option value="all">全部类型</option>
                <option value="tech">科技</option>
                <option value="policy">政策</option>
              </select>
            </label>
            <label className="source-filter">
              <span className="sr-only">采集状态</span>
              <select
                aria-label="采集状态"
                value={status}
                onChange={(e) =>
                  update({ status: e.target.value, view: 'all', error: null })
                }
              >
                <option value="all">全部状态</option>
                {monitorOrder.map((key) => (
                  <option value={key} key={key}>
                    {monitorLabels[key]}
                  </option>
                ))}
              </select>
            </label>
            <label className="source-filter">
              未采集阈值
              <select
                aria-label="未采集阈值"
                value={hours}
                onChange={(e) => update({ hours: e.target.value })}
              >
                <option value="24">24h</option>
                <option value="48">48h</option>
                <option value="168">7天</option>
              </select>
            </label>
          </>
        )}
        {actions && <div className="source-controls-actions">{actions}</div>}
      </div>
      {view !== 'stats' && (
        <div className="source-result-line">
          <span>{filtered.length} 个信源</span>
          {(view === 'attention' || status === 'failed') &&
            errorGroups.slice(0, 3).map(([label, count]) => (
              <button
                className={category === label ? 'active' : ''}
                key={label}
                onClick={() =>
                  update({
                    error: category === label ? null : label,
                    status: category === label ? null : 'failed',
                  })
                }
              >
                {label}
                <b>{count}</b>
              </button>
            ))}
          {(q || category || status !== 'all' || kind !== 'all') && (
            <button
              className="clear-source-filters"
              onClick={() =>
                update({ q: null, error: null, status: null, kind: null })
              }
            >
              清除筛选
              <X size={12} />
            </button>
          )}
          <span className="source-result-note">
            按最近一轮归并 · 空结果不等于失败
          </span>
        </div>
      )}
      {view === 'stats' ? (
        <div className="monitor-statistics">
          <div className="monitor-grid">
            <section className="surface">
              <PanelHeading title="近两周入库变化" />
              {trend ? (
                <TrendChart data={trend} />
              ) : (
                <Empty title="暂无入库趋势" />
              )}
            </section>
            <section className="surface">
              <PanelHeading title="分析覆盖" />
              <Coverage
                label="文章已分析"
                value={stats?.analyzed}
                total={stats?.total}
              />
              <Coverage
                label="政策已分析"
                value={policyStats?.analyzed}
                total={policyStats?.total}
              />
              <p className="snapshot-note">
                未分析数量不等于待处理队列。政策预筛会跳过低相关内容。
              </p>
            </section>
          </div>
          <section className="surface">
            <h2>统计口径</h2>
            <ul className="evidence-list">
              <li>
                同一信源、同一运行编号的请求合并为一轮。备用地址成功则整轮成功；条数取成功请求的最大值，不重复累加。
              </li>
              <li>
                最近12轮按采集次数排列，不是固定时间轴。空结果表示本轮没有内容；跳过不代表停用。
              </li>
              <li>
                久未采集按上方可选时间阈值判断，与文章发布频率分开。状态是历史记录，不代表此刻在线。
              </li>
              <li>
                内容产出统计为累计值。重点占比以已评分内容为分母，至少20条评分才显示比例；不合成信源质量总分。
              </li>
              <li>
                政策仅存最近一次运行，历史不足处留空。信源配置不可用时，只展示数据库中的记录。
              </li>
            </ul>
            <p className="snapshot-note">
              快照时间 {dateLabel(snapshot.loadedAt, true)}。刷新不会触发采集。
            </p>
          </section>
        </div>
      ) : (
        <div className={`source-workbench ${selected ? 'has-selection' : ''}`}>
          <section className="surface source-directory" aria-label="信源目录">
            <div
              ref={listRef}
              className="source-directory-scroll"
              tabIndex={0}
              onScroll={(e) => {
                if (e.currentTarget.clientHeight) {
                  scrollPositions.set(scrollKey, e.currentTarget.scrollTop)
                  if (scrollPositions.size > 12)
                    scrollPositions.delete(scrollPositions.keys().next().value!)
                }
              }}
            >
              {filtered.length ? (
                <table className="source-table">
                  <thead>
                    <tr>
                      <th>信源</th>
                      <th>{view === 'yield' ? '分析覆盖' : '最近一轮'}</th>
                      <th>{view === 'yield' ? '重点占比' : '最近12轮'}</th>
                      <th className="source-success-cell">
                        {view === 'yield' ? '最近发布' : '最近成功'}
                      </th>
                      <th>产出</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((source) => (
                      <tr
                        key={source.id}
                        data-selected={selected?.id === source.id}
                        onClick={() => selectSource(source.id)}
                      >
                        <td>
                          <button
                            className="source-name"
                            onClick={(e) => {
                              e.stopPropagation()
                              selectSource(source.id)
                            }}
                            title={source.name}
                            aria-label={`查看信源 ${source.name}`}
                            aria-pressed={selected?.id === source.id}
                          >
                            {source.name}
                          </button>
                          <small className="source-domain">
                            {source.domain}
                          </small>
                        </td>
                        <td>
                          {view === 'yield' ? (
                            source.contentAvailable ? (
                              <span className="source-ratio">
                                {source.analyzed}
                                <span> / {source.articles} 已析</span>
                              </span>
                            ) : (
                              '—'
                            )
                          ) : (
                            <Status source={source} now={now} hours={hours} />
                          )}
                        </td>
                        <td>
                          {view === 'yield' ? (
                            source.contentAvailable && source.scored >= 20 ? (
                              <div className="source-yield">
                                <span>
                                  {Math.round(
                                    (source.high / source.scored) * 100,
                                  )}
                                  %
                                  <small>
                                    {source.high}/{source.scored}
                                  </small>
                                </span>
                                <progress
                                  value={source.high}
                                  max={source.scored}
                                  aria-label={`${source.name} 重点占比 ${source.high}/${source.scored}`}
                                />
                              </div>
                            ) : (
                              <span className="sample-note">
                                {source.contentAvailable
                                  ? `样本不足 · ${source.scored}条评分`
                                  : '统计不可用'}
                              </span>
                            )
                          ) : (
                            <Heartbeat source={source} />
                          )}
                        </td>
                        <td className="source-success-cell">
                          <time
                            title={dateLabel(
                              view === 'yield'
                                ? source.lastPublished
                                : source.lastSuccess,
                              true,
                            )}
                          >
                            {elapsed(
                              view === 'yield'
                                ? source.lastPublished
                                : source.lastSuccess,
                              now,
                            )}
                          </time>
                        </td>
                        <td>
                          <span className="source-output">
                            {source.contentAvailable ? source.articles : '—'}
                            <small>
                              重点 {source.contentAvailable ? source.high : '—'}
                            </small>
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <Empty
                  title="没有匹配的信源"
                  description={
                    view === 'attention'
                      ? '当前条件下没有需要关注的信源，可切换全部信源。'
                      : '尝试减少筛选条件。'
                  }
                />
              )}
            </div>
          </section>
          <aside className="surface source-detail" aria-label="信源详情">
            {selected ? (
              <>
                <header className="source-detail-header">
                  <div className="title-row">
                    <button
                      className="icon-button source-back"
                      aria-label="返回信源目录"
                      title="返回信源目录"
                      onClick={() => update({ source: null }, true)}
                    >
                      <ArrowLeft size={16} />
                    </button>
                    <h2>{selected.name}</h2>
                  </div>
                  <div className="metadata">
                    <span>
                      {selected.kind === 'tech' ? '科技源' : '政策源'}
                    </span>
                    <span>{selected.domain}</span>
                    <span>
                      {selected.configuration === 'disabled'
                        ? '配置已停用'
                        : selected.configuration === 'historical'
                          ? '不在当前配置'
                          : ''}
                    </span>
                  </div>
                  <div
                    className="document-tabs"
                    role="group"
                    aria-label="信源详情视图"
                  >
                    {[
                      ['history', '运行'],
                      ['signals', selected.kind === 'tech' ? '信号' : '政策'],
                      ...(selected.kind === 'tech' ? [['topics', '专题']] : []),
                    ].map(([key, label]) => (
                      <button
                        key={key}
                        aria-pressed={detailTab === key}
                        onClick={() => {
                          update({ detail: key }, true)
                        }}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </header>
                <div
                  className="source-detail-body"
                  ref={detailRef}
                  tabIndex={0}
                >
                  {detailTab === 'history' ? (
                    <>
                      <div className="source-detail-status">
                        <Status source={selected} now={now} hours={hours} />
                        <span className="timestamp">
                          最近采集 {dateLabel(selected.lastRun, true)}
                        </span>
                      </div>
                      <div className="source-history-heading">
                        <h3>采集记录</h3>
                        <span>旧 → 新</span>
                      </div>
                      <div className="source-history-buttons">
                        {[
                          ...Array(Math.max(0, 12 - selected.runs.length)).fill(
                            null,
                          ),
                          ...selected.runs.slice().reverse(),
                        ].map((run: SourceRun | null, i) =>
                          run ? (
                            <button
                              className={`heartbeat-cell ${run.status}`}
                              key={run.id}
                              title={historyLabel(run)}
                              aria-label={historyLabel(run)}
                              aria-pressed={activeRun?.id === run.id}
                              onClick={() => update({ run: run.id }, true)}
                            >
                              {run.status === 'ok' ? (
                                <Check size={12} />
                              ) : run.status === 'failed' ? (
                                '!'
                              ) : run.status === 'empty' ? (
                                '−'
                              ) : (
                                '·'
                              )}
                            </button>
                          ) : (
                            <span
                              className="heartbeat-cell missing"
                              key={i}
                              title="无历史记录"
                            />
                          ),
                        )}
                      </div>
                      {selected.kind === 'policy' && (
                        <p className="snapshot-note">
                          政策当前只保存最近一次运行，其余历史留空。
                        </p>
                      )}
                      {activeRun ? (
                        <section className="source-run">
                          <div className="metadata">
                            {dateLabel(activeRun.at, true)}
                            <span>{monitorLabels[activeRun.status]}</span>
                          </div>
                          <div className="source-run-numbers">
                            <span>
                              获取 <b>{activeRun.fetched}</b> 条
                            </span>
                            <span>
                              请求 <b>{activeRun.attempts}</b> 次
                            </span>
                            <span>
                              累计{' '}
                              <b>{(activeRun.durationMs / 1000).toFixed(1)}s</b>
                            </span>
                          </div>
                          {activeRun.error && activeRun.status === 'failed' && (
                            <div className="source-error">
                              <TriangleAlert size={16} />
                              <div>
                                <strong>
                                  {errorCategory(activeRun.error)}
                                </strong>
                                <p>{activeRun.error}</p>
                              </div>
                            </div>
                          )}
                          {activeRun.status === 'skipped' && (
                            <p className="snapshot-note">
                              本轮已跳过，日志未提供具体原因。跳过与配置停用分别展示。
                            </p>
                          )}
                          {detail?.attempts.filter(
                            (a) => a.runId === activeRun.id,
                          ).length ? (
                            <details className="disclosure">
                              <summary>请求明细</summary>
                              <div className="attempt-list">
                                {detail.attempts
                                  .filter((a) => a.runId === activeRun.id)
                                  .map((a, i) => (
                                    <div key={i}>
                                      <span className="metadata">
                                        {a.status} ·{' '}
                                        {(a.durationMs / 1000).toFixed(1)}s
                                      </span>
                                      <code>
                                        {a.address || '未记录请求地址'}
                                      </code>
                                      {a.error && <p>{a.error}</p>}
                                    </div>
                                  ))}
                              </div>
                            </details>
                          ) : null}
                        </section>
                      ) : (
                        <Empty
                          title={
                            selected.configuration === 'disabled'
                              ? '该信源已在配置中停用'
                              : '尚无采集记录'
                          }
                        />
                      )}
                      {selected.kind === 'tech' && selected.runs.length > 0 && (
                        <p className="snapshot-note">
                          近{selected.runs.length}轮中，
                          {successShare(selected.runs).successful}/
                          {successShare(selected.runs).total}
                          轮可正常解析（含空结果，跳过不计入）。
                        </p>
                      )}
                      <dl className="policy-facts source-meta">
                        <div>
                          <dt>最近成功</dt>
                          <dd>{dateLabel(selected.lastSuccess, true)}</dd>
                        </div>
                        <div>
                          <dt>最近发布</dt>
                          <dd>{dateLabel(selected.lastPublished, true)}</dd>
                        </div>
                        <div>
                          <dt>订阅地址</dt>
                          <dd>
                            <code>{selected.address || '未记录'}</code>
                          </dd>
                        </div>
                      </dl>
                    </>
                  ) : detailState.loading || detailState.id !== selected.id ? (
                    <div className="loading-skeleton" />
                  ) : detailState.error ? (
                    <div className="empty-state" role="alert">
                      <p>{detailState.error}</p>
                      <button
                        className="soft-button"
                        onClick={() => setRetry((v) => v + 1)}
                      >
                        重试
                      </button>
                    </div>
                  ) : detailTab === 'signals' ? (
                    <>
                      <div className="source-content-counts">
                        <span>
                          收录{' '}
                          <b>
                            {selected.contentAvailable
                              ? selected.articles
                              : '—'}
                          </b>
                        </span>
                        <span>
                          已析{' '}
                          <b>
                            {selected.contentAvailable
                              ? selected.analyzed
                              : '—'}
                          </b>
                        </span>
                        <span>
                          重点{' '}
                          <b>
                            {selected.contentAvailable ? selected.high : '—'}
                          </b>
                        </span>
                      </div>
                      <div
                        className="segments"
                        role="group"
                        aria-label="信源内容筛选"
                      >
                        <button
                          aria-pressed={signalMode === 'latest'}
                          onClick={() => update({ content: 'latest' }, true)}
                        >
                          最新
                        </button>
                        <button
                          aria-pressed={signalMode === 'high'}
                          onClick={() => update({ content: 'high' }, true)}
                        >
                          {selected.kind === 'tech' ? '重点' : '高相关'}
                        </button>
                      </div>
                      <p className="snapshot-note">
                        {signalMode === 'high'
                          ? selected.kind === 'tech'
                            ? '重要性 ≥4'
                            : '政策相关度 ≥4'
                          : '按发布时间排列'}{' '}
                        · 最多展示12条
                      </p>
                      {selected.kind === 'tech' ? (
                        <ArticleRows
                          context={sourceContext}
                          rows={
                            (signalMode === 'high'
                              ? detail?.highArticles
                              : detail?.articles) || []
                          }
                        />
                      ) : (
                        <PolicyRows
                          context={sourceContext}
                          rows={
                            (signalMode === 'high'
                              ? detail?.highPolicies
                              : detail?.policies) || []
                          }
                        />
                      )}
                    </>
                  ) : (
                    <>
                      {detail?.topics.length ? (
                        detail.topics.map((topic) => (
                          <Link
                            key={topic.id}
                            className="source-topic"
                            href={withOrigin(
                              `/topics?id=${topic.id}`,
                              sourceContext?.from,
                            )}
                          >
                            <span>
                              {topic.label}
                              <small>{topic.articles} 篇来自此信源</small>
                            </span>
                            <ChevronRight size={15} />
                          </Link>
                        ))
                      ) : (
                        <Empty
                          title="尚无关联专题"
                          description="文章参与信号聚类后，会显示在这里。"
                        />
                      )}
                    </>
                  )}
                  {detailState.error && detailTab === 'history' && (
                    <div className="data-notice">
                      请求明细暂时不可用
                      <button
                        className="soft-button"
                        onClick={() => setRetry((v) => v + 1)}
                      >
                        重试
                      </button>
                    </div>
                  )}
                  {detail && <DataNotice issues={detail.issues} />}
                </div>
              </>
            ) : (
              <Empty
                title="选择一个信源"
                description="查看采集记录，以及它带来的文章与信号。"
              />
            )}
          </aside>
        </div>
      )}
    </div>
  )
}
