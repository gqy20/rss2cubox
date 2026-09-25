'use client'
import { ScoreIndicator } from './Numbers'
import { type ReactNode, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { safeReturnPath } from '../../lib/reading-context'
import { ReturnLink } from './ReadingNavigation'
import { useWindowReadingPosition } from '../../hooks/useReadingPosition'
import { clearMemory } from '../../lib/reading-memory'
import { ChevronRight } from 'lucide-react'
import type { Prediction, Review } from '../../lib/journal-types'
import { dateLabel, predictionStatus } from '../../lib/journal-utils'
import { Empty, PageHeading } from './Shared'
import { ExportButton, RefreshButton } from './Actions'
import { SearchTrigger } from './SearchPalette'
import Drawer from './Drawer'
import PredictionDetail from './PredictionDetail'
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
  // Legacy multi-open links (?open=1,2) map onto the single-selection drawer.
  const openId =
    targetId ||
    (params.get('open') || '')
      .split(',')
      .find((id) => /^\d+$/.test(id)) ||
    ''
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
  // Scroll memory keys stay per-filter only: embedding the search term would
  // mint a new entry per keyword and evict other pages' memories.
  const setFilter = (value: string) => {
    clearMemory(`window:predictions:${value}`)
    update({ filter: value === 'all' ? null : value, id: null })
  }
  const setSearch = (value: string) => {
    clearMemory(`window:predictions:${filter}`)
    update({ q: value || null, id: null })
  }
  // Draft + debounce: typing must not write history and re-filter on every key.
  const [draft, setDraft] = useState(search)
  useEffect(() => setDraft(search), [search])
  useEffect(() => {
    if (draft === search) return
    const timer = setTimeout(() => setSearch(draft), 300)
    return () => clearTimeout(timer)
  }, [draft, search]) // eslint-disable-line react-hooks/exhaustive-deps
  useWindowReadingPosition(`predictions:${filter}`)
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
      <PageHeading title="预测与复盘" />
      {overview}
      <div className="toolbar">
        {origin && <ReturnLink from={origin} className="context-back" />}
        <div className="segments" role="group" aria-label="预测状态">
          {[
            ['all', '全部判断'],
            ['pending', '待验证'],
            ['reviewed', '已复盘'],
          ].map(([key, label]) => (
            <button
              key={key}
              aria-pressed={filter === key}
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
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <div className="toolbar-actions">
          <SearchTrigger />
          <RefreshButton />
          <ExportButton
            data={{ predictions: rows, reviews }}
            name="prediction-ledger"
          />
        </div>
      </div>
      <div className="prediction-list">
        {rows.length ? (
          rows.map((p) => {
            const id = String(p.id),
              isOpen = openId === id
            return (
              <article
                className={`surface prediction-card${isOpen ? ' is-open' : ''}`}
                key={p.id}
                onClick={() => update({ id })}
              >
                <div className="metadata">
                  <span
                    className={`pill ${p.status === 'pending' ? 'clay' : 'olive'}`}
                  >
                    {predictionStatus[p.status] || p.status}
                  </span>
                  <ScoreIndicator label="置信度" value={p.confidence} />
                  <ChevronRight
                    size={15}
                    className="prediction-open-hint"
                    aria-hidden="true"
                  />
                </div>
                <h2 className="prediction-title">
                  <button
                    type="button"
                    aria-expanded={isOpen}
                    onClick={(e) => {
                      e.stopPropagation()
                      update({ id })
                    }}
                  >
                    {p.prediction_title}
                  </button>
                </h2>
                <p className="summary-body">
                  {p.prediction_body.length > 180
                    ? `${p.prediction_body.slice(0, 180)}…`
                    : p.prediction_body}
                </p>
                <div className="metadata prediction-window">
                  验证窗口 {dateLabel(p.target_start_at)} 至{' '}
                  {dateLabel(p.target_end_at)}
                  <span>{p.cluster_label}</span>
                </div>
              </article>
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
      {(() => {
        const selected = predictions.find((p) => String(p.id) === openId)
        return (
          <Drawer
            open={Boolean(selected)}
            onClose={() => update({ id: null, open: null })}
            label={selected ? `预测详情：${selected.prediction_title}` : '预测详情'}
            header={
              selected && (
                <div className="drawer-heading">
                  <span
                    className={`pill ${selected.status === 'pending' ? 'clay' : 'olive'}`}
                  >
                    {predictionStatus[selected.status] || selected.status}
                  </span>
                  <ScoreIndicator label="置信度" value={selected.confidence} />
                </div>
              )
            }
          >
            {selected && (
              <>
                <h2 className="drawer-title">{selected.prediction_title}</h2>
                <div className="metadata prediction-window">
                  验证窗口 {dateLabel(selected.target_start_at)} 至{' '}
                  {dateLabel(selected.target_end_at)}
                  <span>{selected.cluster_label}</span>
                </div>
                <PredictionDetail
                  prediction={selected}
                  reviews={reviews.filter(
                    (r) => r.prediction_id === selected.id,
                  )}
                  from={from}
                />
              </>
            )}
          </Drawer>
        )
      })()}
    </>
  )
}
