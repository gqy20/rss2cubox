'use client'
import { useState } from 'react'
import Link from 'next/link'
import type { Prediction, Review } from '../../lib/journal-types'
import { dateLabel, predictionStatus } from '../../lib/journal-utils'
import { Empty, JsonEvidence } from './Shared'
import { ExportButton } from './Actions'
export default function Predictions({
  predictions,
  reviews,
  initialId,
}: {
  predictions: Prediction[]
  reviews: Review[]
  initialId?: string
}) {
  const [filter, setFilter] = useState('all'),
    [search, setSearch] = useState('')
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
  return (
    <>
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
        <ExportButton
          data={{ predictions: rows, reviews }}
          name="prediction-ledger"
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
                open={String(p.id) === initialId ? true : undefined}
              >
                <summary>
                  <div className="metadata">
                    <span
                      className={`pill ${p.status === 'pending' ? 'clay' : 'olive'}`}
                    >
                      {predictionStatus[p.status] || p.status}
                    </span>
                    <span>
                      置信度{' '}
                      {p.confidence == null ? '未记录' : `${p.confidence}/5`}
                    </span>
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
                    href={`/topics?id=${p.signal_cluster_id}`}
                  >
                    阅读关联专题 →
                  </Link>
                )}
                {related.length ? (
                  related.map((review) => (
                    <section className="review-note" key={review.id}>
                      <div className="metadata">
                        复盘于 {dateLabel(review.reviewed_at, true)}
                        <span>评分 {review.score}</span>
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
