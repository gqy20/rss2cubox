'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import {
  ArrowLeft,
  Brain,
  ChevronDown,
  ChevronUp,
  Target,
  TrendingUp,
  Sparkles,
  Clock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  BarChart3,
  Tag,
} from 'lucide-react'
import { Logo } from '../utils'
import MotionMount from '../MotionMount'

type SignalCluster = {
  id: number
  label: string
  normalized_label: string
  signal_type: number | null
  status: string
  summary: string | null
  entities: string[]
  watch_keywords: string[]
  first_seen_at: string | null
  last_seen_at: string | null
  article_count: number
  source_count: number
  avg_importance: number | null
  avg_confidence: number | null
  prediction_score_avg: number | null
  created_at: string
  updated_at: string
  linked_articles: Array<{ article_id: string; relevance_score: number | null }>
}

type TrendPrediction = {
  id: number
  prediction_type: number
  created_at: string
  target_start_at: string
  target_end_at: string
  horizon_days: number
  prediction_title: string
  prediction_body: string
  watch_keywords: string[]
  expected_evidence: Record<string, unknown>
  disconfirming_evidence: string | null
  baseline_metrics: Record<string, unknown>
  confidence: number | null
  status: string
  cluster_label: string | null
  cluster_key: string | null
}

type PredictionReview = {
  id: number
  prediction_id: number
  reviewed_at: string
  score: number
  hit_level: string
  supporting_articles: string[]
  contradicting_articles: string[]
  actual_observation: string | null
  why_score: string | null
  improvement_advice: string | null
  review_metrics: Record<string, unknown>
  prediction_title: string
  prediction_body: string
  prediction_status: string
  cluster_label: string | null
}

const SIGNAL_TYPE_MAP: Record<number, string> = {
  1: '延续',
  2: '加速',
  3: '扩散',
  4: '反转',
  5: '新信号',
}

const STATUS_COLORS: Record<string, string> = {
  new: 'var(--status-new)',
  warming: 'var(--status-warming)',
  bursting: 'var(--status-bursting)',
  mature: 'var(--status-mature)',
  declining: 'var(--status-declining)',
}

const STATUS_LABELS: Record<string, string> = {
  new: '新发现',
  warming: '升温中',
  bursting: '爆发期',
  mature: '成熟期',
  declining: '衰退中',
}

const PREDICTION_TYPE_MAP: Record<number, string> = {
  1: '延续',
  2: '转阶段',
  3: '扩散',
  4: '反转',
  5: '迟到验证',
}

const HIT_LEVEL_COLORS: Record<string, string> = {
  miss: '#ef4444',
  weak: '#f97316',
  partial: '#fbbf24',
  strong: '#34d399',
  exact: '#22c55e',
}

const HIT_LEVEL_ORDER = ['exact', 'strong', 'partial', 'weak', 'miss'] as const
const HIT_LEVEL_LABELS: Record<string, string> = {
  exact: '精确命中',
  strong: '强验证',
  partial: '部分命中',
  weak: '弱信号',
  miss: '未命中',
}

const PRED_STATUS_COLORS: Record<string, string> = {
  pending: '#fbbf24',
  reviewed: '#60a5fa',
  hit: '#34d399',
  miss: '#ef4444',
}
const PRED_STATUS_ORDER = ['pending', 'reviewed', 'hit', 'miss'] as const
const PRED_STATUS_LABELS: Record<string, string> = {
  pending: '待验证',
  reviewed: '已复盘',
  hit: '命中',
  miss: '未命中',
}

const STATUS_ORDER = ['bursting', 'warming', 'new', 'mature', 'declining'] as const

/** Prediction Review 根因修复部署时间（COALESCE + split-keyword 修复） */
const FIX_DEPLOYED_AT = new Date('2026-05-30T13:26:39+08:00').getTime()

function isLegacyReview(reviewedAt: string | null): boolean {
  if (!reviewedAt) return true
  try { return new Date(reviewedAt).getTime() < FIX_DEPLOYED_AT }
  catch { return true }
}

function isOverdue(targetEndAt: string | null): boolean {
  if (!targetEndAt) return false
  try { return new Date(targetEndAt).getTime() < Date.now() }
  catch { return false }
}

function formatA11yName(value: string): string {
  return value.replace(/["“”]+/g, '').replace(/\s+/g, ' ').trim()
}

function formatDate(iso: string | null): string {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleDateString('zh-CN', {
      timeZone: 'Asia/Shanghai',
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function formatDateShort(iso: string | null): string {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleDateString('zh-CN', {
      timeZone: 'Asia/Shanghai',
      month: 'numeric',
      day: 'numeric',
    })
  } catch {
    return iso
  }
}

function MetricDots({ value, max = 5, blue }: { value: number; max?: number; blue?: boolean }) {
  const clamped = Math.max(0, Math.min(max, Math.round(value)))
  return (
    <div className="pred-metric-bar">
      {Array.from({ length: max }, (_, i) => (
        <div key={i} className={`pred-metric-dot${i < clamped ? (blue ? ' filled-blue' : ' filled') : ''}`} />
      ))}
    </div>
  )
}

export default function PredictionsPage() {
  const [clusters, setClusters] = useState<SignalCluster[]>([])
  const [predictions, setPredictions] = useState<TrendPrediction[]>([])
  const [reviews, setReviews] = useState<PredictionReview[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedCluster, setExpandedCluster] = useState<number | null>(null)
  const [expandedPrediction, setExpandedPrediction] = useState<number | null>(null)
  const [activeSection, setActiveSection] = useState<string>('clusters')

  useEffect(() => {
    Promise.all([
      fetch('/api/predictions/clusters').then((r) => r.json()),
      fetch('/api/predictions/predictions').then((r) => r.json()),
      fetch('/api/predictions/reviews').then((r) => r.json()),
    ])
      .then(([clustersRes, predictionsRes, reviewsRes]) => {
        setClusters(clustersRes.data || [])
        setPredictions(predictionsRes.data || [])
        setReviews(reviewsRes.data || [])
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const statusStats = clusters.reduce(
    (acc, c) => {
      acc[c.status] = (acc[c.status] || 0) + 1
      return acc
    },
    {} as Record<string, number>,
  )

  const pendingCount = predictions.filter((p) => p.status === 'pending').length
  const overdueCount = predictions.filter((p) => p.status === 'pending' && isOverdue(p.target_end_at)).length
  const completedCount = predictions.filter((p) => p.status !== 'pending').length
  const avgScore = reviews.length > 0
    ? (reviews.reduce((s, r) => s + r.score, 0) / reviews.length).toFixed(1)
    : '-'

  // Predictions status distribution
  const predStatusStats = predictions.reduce(
    (acc, p) => { acc[p.status] = (acc[p.status] || 0) + 1; return acc },
    {} as Record<string, number>,
  )

  const activePredictions = [...predictions]
    .sort((a, b) => {
      const aOverdue = a.status === 'pending' && isOverdue(a.target_end_at)
      const bOverdue = b.status === 'pending' && isOverdue(b.target_end_at)
      if (aOverdue !== bOverdue) return aOverdue ? -1 : 1
      if (a.status === 'pending' && b.status !== 'pending') return -1
      if (a.status !== 'pending' && b.status === 'pending') return 1
      return new Date(a.target_end_at || a.created_at).getTime() - new Date(b.target_end_at || b.created_at).getTime()
    })
    .slice(0, 8)

  const recentReviews = [...reviews]
    .sort((a, b) => new Date(b.reviewed_at).getTime() - new Date(a.reviewed_at).getTime())
    .slice(0, 3)

  // Reviews hit_level distribution
  const hitLevelStats = reviews.reduce(
    (acc, r) => { acc[r.hit_level] = (acc[r.hit_level] || 0) + 1; return acc },
    {} as Record<string, number>,
  )

  if (loading) {
    return (
      <main className="main predictions-scrollable">
        <div className="predictions-page">
          <PredictionsHeader />
          <div className="predictions-loading">
            <div className="predictions-spinner" />
            <span>正在加载预测循环数据...</span>
          </div>
        </div>
      </main>
    )
  }

  if (error) {
    return (
      <main className="main predictions-scrollable">
        <div className="predictions-page">
          <PredictionsHeader />
          <div className="predictions-error">
            <AlertTriangle size={20} />
            <span>加载失败：{error}</span>
          </div>
        </div>
      </main>
    )
  }

  return (
    <main className="main predictions-scrollable">
      <div className="predictions-page">
        <MotionMount scope="predictions" />
        <PredictionsHeader />

        <div className="prediction-lab-status">
          <button onClick={() => document.getElementById('section-clusters')?.scrollIntoView({ behavior: 'smooth' })}>
            <span>Evidence Pool</span><strong>{clusters.length}</strong>
          </button>
          <button onClick={() => document.getElementById('section-predictions')?.scrollIntoView({ behavior: 'smooth' })}>
            <span>Active Predictions</span><strong>{pendingCount}</strong>
          </button>
          <button onClick={() => document.getElementById('section-predictions')?.scrollIntoView({ behavior: 'smooth' })}>
            <span>Overdue</span><strong>{overdueCount}</strong>
          </button>
          <button onClick={() => document.getElementById('section-reviews')?.scrollIntoView({ behavior: 'smooth' })}>
            <span>Avg Review</span><strong>{avgScore}</strong>
          </button>
        </div>

        <div className="predictions-lab-hero">
          <div className="predictions-main">
            {/* Predictions */}
            <section id="section-predictions" className="pred-section">
              <div className="pred-section-head">
                <Target size={18} />
                <h2>Active Predictions</h2>
                <span className="pred-section-count">{activePredictions.length}/{predictions.length}</span>
              </div>
              {activePredictions.length === 0 ? (
                <div className="pred-empty">
                  暂无趋势预测。预测基于信号聚类生成，需 prediction loop generate 阶段成功产出。
                </div>
              ) : (
                <div className="pred-list">
                  {activePredictions.map((pred) => (
                    <div
                      key={pred.id}
                      className={`pred-prediction-card${expandedPrediction === pred.id ? ' expanded' : ''}`}
                      onClick={() => setExpandedPrediction(expandedPrediction === pred.id ? null : pred.id)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          setExpandedPrediction(expandedPrediction === pred.id ? null : pred.id)
                        }
                      }}
                      role="button"
                      tabIndex={0}
                      aria-expanded={expandedPrediction === pred.id}
                      aria-label={`预测：${formatA11yName(pred.prediction_title)}`}
                    >
                      <div className="pred-prediction-head">
                        <div className="pred-prediction-title-row">
                          {pred.status === 'pending' ? (
                            isOverdue(pred.target_end_at) ? (
                              <AlertTriangle size={14} style={{ color: '#ef4444', flexShrink: 0 }} />
                            ) : (
                              <Clock size={14} style={{ color: '#fbbf24', flexShrink: 0 }} />
                            )
                          ) : pred.status === 'hit' ? (
                            <CheckCircle2 size={14} style={{ color: '#34d399', flexShrink: 0 }} />
                          ) : (
                            <XCircle size={14} style={{ color: '#ef4444', flexShrink: 0 }} />
                          )}
                          <h3>{pred.prediction_title}</h3>
                        </div>
                        <div className="pred-prediction-meta">
                          {pred.prediction_type && (
                            <span className="pred-badge">{PREDICTION_TYPE_MAP[pred.prediction_type] || `类型${pred.prediction_type}`}</span>
                          )}
                          <span className="pred-badge pred-badge-muted">{pred.status}</span>
                          {pred.status === 'pending' && isOverdue(pred.target_end_at) && (
                            <span className="pred-badge" style={{ color: '#ef4444', background: 'rgba(239,68,68,0.1)' }}>
                              已过期
                            </span>
                          )}
                          {pred.confidence != null && pred.confidence > 0 && (
                            <span className="pred-badge pred-badge-muted">置信度 {pred.confidence}/5</span>
                          )}
                          {pred.cluster_label && (
                            <span className="pred-badge pred-badge-accent">{pred.cluster_label}</span>
                          )}
                        </div>
                      </div>
                      <p className="pred-prediction-body">{pred.prediction_body}</p>
                      <div className="pred-prediction-footer">
                        <span className="pred-time-muted">
                          {formatDateShort(pred.target_start_at)} ~ {formatDateShort(pred.target_end_at)}（{pred.horizon_days}天）
                        </span>
                        <span className="pred-time-muted">创建于 {formatDate(pred.created_at)}</span>
                      </div>
                      {expandedPrediction === pred.id && (
                        <div className={`pred-cluster-expanded${expandedPrediction === pred.id ? ' open' : ''}`}>
                          {pred.watch_keywords && pred.watch_keywords.length > 0 && (
                            <div className="pred-expanded-row">
                              <span className="pred-expanded-label">监控关键词</span>
                              <div className="pred-tags">
                                {pred.watch_keywords.map((kw, i) => (
                                  <span key={i} className="pred-tag pred-tag-keyword">{kw}</span>
                                ))}
                              </div>
                            </div>
                          )}
                          {pred.expected_evidence && Object.keys(pred.expected_evidence).length > 0 && (
                            <div className="pred-expanded-row">
                              <span className="pred-expanded-label">预期证据</span>
                              <pre className="pred-json">{JSON.stringify(pred.expected_evidence, null, 2)}</pre>
                            </div>
                          )}
                          {pred.disconfirming_evidence && (
                            <div className="pred-expanded-row">
                              <span className="pred-expanded-label">证伪标准</span>
                              <span>{pred.disconfirming_evidence}</span>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* Reviews */}
            <section id="section-reviews" className="pred-section">
              <div className="pred-section-head">
                <BarChart3 size={18} />
                <h2>预测复盘</h2>
                <span className="pred-section-count">{reviews.length}</span>
              </div>
              {reviews.length === 0 ? (
                <div className="pred-empty">
                  暂无预测复盘数据。复盘在预测窗口结束后自动执行。
                </div>
              ) : (
                <div className="pred-list">
                  {reviews.map((review) => (
                    <div key={review.id} className="pred-review-card">
                      {/* Left: score column */}
                      <div className="pred-review-score-col">
                        <div className="pred-review-score" style={{ color: HIT_LEVEL_COLORS[review.hit_level] || '#8aa3be' }}>
                          <strong>{review.score}</strong>/5
                        </div>
                        <span className="pred-badge" style={{ color: HIT_LEVEL_COLORS[review.hit_level], fontSize: 'var(--fs-micro)', padding: '1px 6px' }}>
                          {review.hit_level}
                        </span>
                        {isLegacyReview(review.reviewed_at) && (
                          <span className="pred-badge pred-badge-muted" style={{ fontSize: '10px', padding: '1px 5px' }} title="此复盘生成于根因修复（COALESCE+关键词拆分）部署之前，候选文章可能为空导致评分偏低">
                            修复前
                          </span>
                        )}
                      </div>

                      {/* Right: content column */}
                      <div className="pred-review-body">
                        <div className="pred-review-meta-row">
                          <span className="pred-badge pred-badge-muted">{review.prediction_status}</span>
                          {review.cluster_label && (
                            <span className="pred-badge pred-badge-accent">{review.cluster_label}</span>
                          )}
                          <span
                            className="pred-badge pred-badge-muted"
                            style={{ cursor: 'pointer' }}
                            onClick={(e) => {
                              e.stopPropagation()
                              const el = document.getElementById(`section-predictions`)
                              el?.scrollIntoView({ behavior: 'smooth' })
                              setActiveSection('predictions')
                            }}
                            title="点击跳转到对应的趋势预测"
                          >
                            预测 #{review.prediction_id}
                          </span>
                        </div>
                        <h3 className="pred-review-title">{review.prediction_title}</h3>
                      {review.actual_observation && (
                        <div className="pred-review-field">
                          <span className="pred-review-label">实际观察</span>
                          <p>{review.actual_observation}</p>
                        </div>
                      )}
                      {review.why_score && (
                        <div className="pred-review-field">
                          <span className="pred-review-label">评分理由</span>
                          <p>{review.why_score}</p>
                        </div>
                      )}
                      {review.improvement_advice && (
                        <div className="pred-review-field">
                          <span className="pred-review-label">改进建议</span>
                          <p>{review.improvement_advice}</p>
                        </div>
                      )}
                      <div className="pred-review-footer">
                        {review.supporting_articles && review.supporting_articles.length > 0 && (
                          <span className="pred-time-muted">支持 {review.supporting_articles.length} 篇</span>
                        )}
                        {review.contradicting_articles && review.contradicting_articles.length > 0 && (
                          <span className="pred-time-muted">矛盾 {review.contradicting_articles.length} 篇</span>
                        )}
                        <span className="pred-time-muted">复盘于 {formatDate(review.reviewed_at)}</span>
                      </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>

          <aside className="prediction-review-pulse">
            <div className="pred-section-head">
              <BarChart3 size={18} />
              <h2>Review Pulse</h2>
              <span className="pred-section-count">{reviews.length}</span>
            </div>
            <div className="review-pulse-score">
              <span>平均复盘分</span>
              <strong>{avgScore}</strong>
            </div>
            {reviews.length > 0 && (
              <>
                <div className="pred-status-bar">
                  {HIT_LEVEL_ORDER.map((level) => {
                    const count = hitLevelStats[level] || 0
                    if (count === 0) return null
                    return (
                      <div
                        key={level}
                        className="pred-status-bar-segment"
                        style={{
                          width: `${(count / reviews.length) * 100}%`,
                          background: HIT_LEVEL_COLORS[level],
                        }}
                      />
                    )
                  })}
                </div>
                <div className="pred-status-legend">
                  {HIT_LEVEL_ORDER.map((level) => {
                    const count = hitLevelStats[level] || 0
                    if (count === 0) return null
                    return (
                      <span key={level} className="pred-status-legend-item">
                        <span className="pred-status-legend-dot" style={{ background: HIT_LEVEL_COLORS[level] }} />
                        {HIT_LEVEL_LABELS[level]} {count}
                      </span>
                    )
                  })}
                </div>
              </>
            )}
            <div className="review-pulse-list">
              {recentReviews.map((review) => (
                <div key={review.id} className="review-pulse-item">
                  <strong>{review.score}/5</strong>
                  <span>{review.prediction_title}</span>
                </div>
              ))}
            </div>
          </aside>
        </div>

        <section id="section-clusters" className="pred-section evidence-pool-section">
          <div className="pred-section-head">
            <Brain size={18} />
            <h2>Evidence Pool</h2>
            <span className="pred-section-count">{clusters.length}</span>
          </div>
          {clusters.length === 0 ? (
            <div className="pred-empty">暂无信号聚类数据，等待 prediction loop cluster 阶段产出。</div>
          ) : (
            <div className="pred-cluster-grid">
              {clusters.map((cluster) => (
                <div
                  key={cluster.id}
                  className={`pred-cluster-card${expandedCluster === cluster.id ? ' expanded' : ''}`}
                  onClick={() => setExpandedCluster(expandedCluster === cluster.id ? null : cluster.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      setExpandedCluster(expandedCluster === cluster.id ? null : cluster.id)
                    }
                  }}
                  role="button"
                  tabIndex={0}
                  aria-expanded={expandedCluster === cluster.id}
                  aria-label={`证据聚类：${formatA11yName(cluster.label)}`}
                >
                  <div className="pred-cluster-head">
                    <div className="pred-cluster-title-row">
                      <span
                        className="pred-cluster-status"
                        style={{ background: STATUS_COLORS[cluster.status] || '#6b7280' }}
                      />
                      <h3>{cluster.label}</h3>
                    </div>
                    <div className="pred-cluster-meta">
                      {cluster.signal_type && (
                        <span className="pred-badge">{SIGNAL_TYPE_MAP[cluster.signal_type] || `类型${cluster.signal_type}`}</span>
                      )}
                      <span className="pred-badge pred-badge-muted">{STATUS_LABELS[cluster.status] || cluster.status}</span>
                      <span className="pred-badge pred-badge-muted">{cluster.article_count} 篇</span>
                    </div>
                  </div>
                  {cluster.summary && <p className="pred-cluster-summary">{cluster.summary}</p>}

                  <div className="pred-cluster-metrics">
                    {cluster.avg_importance != null && (
                      <div className="pred-metric">
                        <span className="pred-metric-label">重要性</span>
                        <MetricDots value={cluster.avg_importance} />
                      </div>
                    )}
                    {cluster.avg_confidence != null && cluster.avg_confidence > 0 && (
                      <div className="pred-metric">
                        <span className="pred-metric-label">置信度</span>
                        <MetricDots value={cluster.avg_confidence} blue />
                      </div>
                    )}
                  </div>

                  <div className="pred-cluster-footer">
                    {cluster.entities && cluster.entities.length > 0 && (
                      <div className="pred-tags">
                        {cluster.entities.slice(0, 3).map((e, i) => (
                          <span key={i} className="pred-tag pred-tag-entity">{e}</span>
                        ))}
                        {cluster.entities.length > 3 && <span className="pred-tag">+{cluster.entities.length - 3}</span>}
                      </div>
                    )}
                    <span className="pred-time-muted">
                      {formatDate(cluster.updated_at)}
                    </span>
                  </div>

                  {expandedCluster === cluster.id && (
                    <div className={`pred-cluster-expanded${expandedCluster === cluster.id ? ' open' : ''}`}>
                      {cluster.watch_keywords && cluster.watch_keywords.length > 0 && (
                        <div className="pred-expanded-row">
                          <span className="pred-expanded-label">监控关键词</span>
                          <div className="pred-tags">
                            {cluster.watch_keywords.map((kw, i) => (
                              <span key={i} className="pred-tag pred-tag-keyword">{kw}</span>
                            ))}
                          </div>
                        </div>
                      )}
                      <div className="pred-expanded-row">
                        <span className="pred-expanded-label">评分</span>
                        <div className="pred-scores">
                          {cluster.source_count > 0 && <span>来源 <strong>{cluster.source_count}</strong></span>}
                          {cluster.linked_articles && cluster.linked_articles.length > 0 && (
                            <span>关联 <strong>{cluster.linked_articles.length}</strong> 篇</span>
                          )}
                        </div>
                      </div>
                      {cluster.first_seen_at && (
                        <div className="pred-expanded-row">
                          <span className="pred-expanded-label">时间窗口</span>
                          <span className="pred-time-muted">
                            {formatDateShort(cluster.first_seen_at)} ~ {formatDateShort(cluster.last_seen_at)}
                          </span>
                        </div>
                      )}
                    </div>
                  )}
                  <div className="pred-expand-hint">
                    {expandedCluster === cluster.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  )
}

function PredictionsHeader() {
  return (
    <div className="header-container predictions-header">
      <div>
        <div className="dashboard-brand">
          <Link href="/" className="predictions-back" aria-label="返回主控制台">
            <ArrowLeft size={20} />
          </Link>
          <Logo size={36} />
          <h1 className="h1">Prediction Lab</h1>
        </div>
        <div className="muted dashboard-updated">
          Signal Cluster → Trend Prediction → Prediction Review
        </div>
      </div>
    </div>
  )
}
