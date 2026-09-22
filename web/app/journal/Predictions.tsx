'use client'
import { ScoreIndicator } from './Numbers'
import { type ReactNode } from 'react'
import { useSearchParams } from 'next/navigation'
import { safeReturnPath, withOrigin } from '../../lib/reading-context'
import { ReturnLink } from './ReadingNavigation'
import { useWindowReadingPosition } from '../../hooks/useReadingPosition'
import { clearMemory } from '../../lib/reading-memory'
import Link from 'next/link'
import type { Prediction, Review } from '../../lib/journal-types'
import { dateLabel, predictionStatus } from '../../lib/journal-utils'
import { Empty, JsonEvidence, PageHeading } from './Shared'
import { ExportButton, RefreshButton } from './Actions'
export default function Predictions({
  predictions,
  reviews,
  initialId,
  overview,
}: {
  predictions: Prediction[]
  reviews: Review[]
  initialId?: string
  overview?: ReactNode
}) {
  const params = useSearchParams(),
    query = params.toString(),
    targetId = params.get('id') || ''
  const filter = ['pending', 'reviewed'].includes(params.get('filter') || '')
      ? params.get('filter')!
      : 'all',
    search = params.get('q') || ''
  const origin = safeReturnPath(params.get('from'))
  const expanded = new Set(
    (params.has('open') ? params.get('open') || '' : targetId)
      .split(',')
      .filter((id) => /^\d+$/.test(id)),
  )
  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(query)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key)
      else next.set(key, value)
    }
    const href = `/predictions${next.size ? '?' + next : ''}`
    if (href !== `/predictions${query ? '?' + query : ''}`)
      window.history.replaceState(null, '', href)
  }
  const setFilter = (value: string) => {
    clearMemory(`window:predictions:${value}:${search}`)
    update({ filter: value === 'all' ? null : value, id: null })
  }
  const setSearch = (value: string) => {
    clearMemory(`window:predictions:${filter}:${value}`)
    update({ q: value || null, id: null })
  }
  useWindowReadingPosition(`predictions:${filter}:${search}`)
  const from = `/predictions${query ? '?' + query : ''}`
  const rows = predictions.filter(
    (p) =>
      (filter === 'all' ||
        (filter === 'reviewed'
          ? p.status !== 'pending'
          : p.status === filter)) &&
      `${p.prediction_title} ${p.cluster_label || ''}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  )
  rows.sort(
    (a, b) =>
      Number(String(b.id) === targetId) - Number(String(a.id) === targetId),
  )
  return (
    <>
      <PageHeading title="预测与复盘">
        {origin && <ReturnLink from={origin} className="context-back" />}
        <RefreshButton />
        <ExportButton
          data={{ predictions: rows, reviews }}
          name="prediction-ledger"
        />
      </PageHeading>
      {overview}
      <div className="toolbar">
        <div className="segments" role="tablist" aria-label="预测状态">
          {[
            ['all', '全部判断'],
            ['pending', '待验证'],
            ['reviewed', '已复盘'],
          ].map(([key, label]) => (
            <button
              key={key}
              role="tab"
              aria-selected={filter === key}
              onClick={() => setFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <input
          type="search"
          aria-label="搜索预测"
          placeholder="搜索判断或专题…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      <div className="prediction-list">
        {rows.length ? (
          rows.map((p) => {
            const related = reviews.filter((r) => r.prediction_id === p.id)
            return (
              <details
                className="surface prediction-card"
                key={p.id}
                open={expanded.has(String(p.id))}
                onToggle={(e) => {
                  if (!e.currentTarget.isConnected) return
                  const card = e.currentTarget
                  const ids = new Set(expanded)
                  if (card.open) {
                    ids.add(String(p.id))
                    requestAnimationFrame(() =>
                      card.scrollIntoView({ block: 'start', behavior: 'smooth' }),
                    )
                  } else {
                    ids.delete(String(p.id))
                  }
                  update({ open: [...ids].join(',') || 'none' })
                }}
              >
                <summary>
                  <div className="metadata">
                    <span
                      className={`pill ${p.status === 'pending' ? 'clay' : 'olive'}`}
                    >
                      {predictionStatus[p.status] || p.status}
                    </span>
                    <ScoreIndicator label="置信度" value={p.confidence} />
                    <span className="expand-label">展开依据与复盘</span>
                  </div>
                  <h2>{p.prediction_title}</h2>
                  <p className="summary-body">
                    {p.prediction_body.length > 180
                      ? `${p.prediction_body.slice(0, 180)}…`
                      : p.prediction_body}
                  </p>
                  <div className="metadata" style={{ marginTop: 15 }}>
                    验证窗口 {dateLabel(p.target_start_at)} 至{' '}
                    {dateLabel(p.target_end_at)}
                    <span>{p.cluster_label}</span>
                  </div>
                </summary>
                <div className="document-section">
                  <h3>原始判断</h3>
                  <p>{p.prediction_body}</p>
                </div>
                <div className="document-section">
                  <h3>预期验证证据</h3>
                  <JsonEvidence value={p.expected_evidence} />
                </div>
                <div className="document-section">
                  <h3>什么会推翻这个判断</h3>
                  <p>{p.disconfirming_evidence || '未记录反证条件'}</p>
                </div>
                {p.signal_cluster_id && (
                  <Link
                    className="text-link"
                    href={withOrigin(`/topics?id=${p.signal_cluster_id}`, from)}
                  >
                    阅读关联专题 →
                  </Link>
                )}
                {related.length ? (
                  related.map((review) => (
                    <section className="review-note" key={review.id}>
                      <div className="metadata">
                        复盘于 {dateLabel(review.reviewed_at, true)}
                        <ScoreIndicator label="复盘评分" value={review.score} />
                        <span>
                          {(
                            {
                              exact: '精确命中',
                              strong: '强验证',
                              partial: '部分命中',
                              weak: '弱验证',
                              miss: '未命中',
                            } as Record<string, string>
                          )[review.hit_level] || review.hit_level}
                        </span>
                      </div>
                      <p>{review.actual_observation}</p>
                      <p>{review.why_score}</p>
                      {review.improvement_advice && (
                        <p>
                          <strong>改进建议：</strong>
                          {review.improvement_advice}
                        </p>
                      )}
                      <details className="disclosure">
                        <summary>支持与反对材料</summary>
                        <div>
                          <h3>支持材料</h3>
                          <JsonEvidence value={review.supporting_articles} />
                          <h3>反对材料</h3>
                          <JsonEvidence value={review.contradicting_articles} />
                        </div>
                      </details>
                    </section>
                  ))
                ) : (
                  <p className="snapshot-note">
                    这条判断尚无复盘记录。待验证不代表已经发生或已经命中。
                  </p>
                )}
              </details>
            )
          })
        ) : (
          <section className="surface">
            <Empty
              title="当前筛选下没有预测"
              description="尝试其他状态，或等待下一轮预测生成。"
            />
          </section>
        )}
      </div>
    </>
  )
}
