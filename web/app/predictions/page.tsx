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
  FileText,
  Layers,
} from 'lucide-react'
import { Logo } from '../utils'

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

const STATUS_ORDER = ['bursting', 'warming', 'new', 'mature', 'declining'] as const

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
  const completedCount = predictions.filter((p) => p.status !== 'pending').length
  const avgScore = reviews.length > 0
    ? (reviews.reduce((s, r) => s + r.score, 0) / reviews.length).toFixed(1)
    : '-'

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
        <PredictionsHeader />

        <div className="predictions-layout">
          {/* ── Left sidebar ── */}
          <aside className="predictions-sidebar">
            {/* KPI: Clusters */}
            <div className="pred-kpi-card pred-kpi-card-blue">
              <Sparkles size={14} className="pred-kpi-icon" />
              <div className="pred-kpi-value">{clusters.length}</div>
              <div className="pred-kpi-label">信号聚类</div>
              {clusters.length > 0 && (
                <>
                  <div className="pred-status-bar">
                    {STATUS_ORDER.map((status) => {
                      const count = statusStats[status] || 0
                      if (count === 0) return null
                      return (
                        <div
                          key={status}
                          className="pred-status-bar-segment"
                          style={{
                            width: `${(count / clusters.length) * 100}%`,
                            background: STATUS_COLORS[status],
                          }}
                        />
                      )
                    })}
                  </div>
                  <div className="pred-status-legend">
                    {STATUS_ORDER.map((status) => {
                      const count = statusStats[status] || 0
                      if (count === 0) return null
                      return (
                        <span key={status} className="pred-status-legend-item">
                          <span className="pred-status-legend-dot" style={{ background: STATUS_COLORS[status] }} />
                          {STATUS_LABELS[status]} {count}
                        </span>
                      )
                    })}
                  </div>
                </>
              )}
            </div>

            {/* KPI: Predictions */}
            <div className="pred-kpi-card pred-kpi-card-teal">
              <Target size={14} className="pred-kpi-icon" />
              <div className="pred-kpi-value">{predictions.length}</div>
              <div className="pred-kpi-label">趋势预测</div>
              <div className="pred-kpi-detail">
                {predictions.length > 0
                  ? `${pendingCount} 待验证 / ${completedCount} 已完成`
                  : '暂无数据'}
              </div>
            </div>

            {/* KPI: Reviews */}
            <div className="pred-kpi-card pred-kpi-card-purple">
              <BarChart3 size={14} className="pred-kpi-icon" />
              <div className="pred-kpi-value">{reviews.length}</div>
              <div className="pred-kpi-label">预测复盘</div>
              <div className="pred-kpi-detail">
                {reviews.length > 0 ? `平均分 ${avgScore}` : '暂无数据'}
              </div>
            </div>

            {/* Nav links */}
            <div className="pred-nav-links">
              <button
                className={`pred-nav-link${activeSection === 'clusters' ? ' active' : ''}`}
                onClick={() => {
                  setActiveSection('clusters')
                  document.getElementById('section-clusters')?.scrollIntoView({ behavior: 'smooth' })
                }}
              >
                <Layers size={14} />
                信号聚类
                <span className="pred-nav-link-count">{clusters.length}</span>
              </button>
              <button
                className={`pred-nav-link${activeSection === 'predictions' ? ' active' : ''}`}
                onClick={() => {
                  setActiveSection('predictions')
                  document.getElementById('section-predictions')?.scrollIntoView({ behavior: 'smooth' })
                }}
              >
                <TrendingUp size={14} />
                趋势预测
                <span className="pred-nav-link-count">{predictions.length}</span>
              </button>
              <button
                className={`pred-nav-link${activeSection === 'reviews' ? ' active' : ''}`}
                onClick={() => {
                  setActiveSection('reviews')
                  document.getElementById('section-reviews')?.scrollIntoView({ behavior: 'smooth' })
                }}
              >
                <FileText size={14} />
                预测复盘
                <span className="pred-nav-link-count">{reviews.length}</span>
              </button>
            </div>
          </aside>

          {/* ── Right main content ── */}
          <div className="predictions-main">
            {/* Clusters */}
            <section id="section-clusters" className="pred-section">
              <div className="pred-section-head">
                <Brain size={18} />
                <h2>信号聚类</h2>
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
                      onClick={() => setExpandedCluster(expendedCluster === cluster.id ? null : cluster.id)}
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

                      {/* Metric bars */}
                      <div className="pred-cluster-metrics">
                        {cluster.avg_importance != null && (
                          <div className="pred-metric">
                            <span className="pred-metric-label">重要性</span>
                            <MetricDots value={cluster.avg_importance} />
                          </div>
                        )}
                        {cluster.avg_confidence != null && (
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

            {/* Predictions */}
            <section id="section-predictions" className="pred-section">
              <div className="pred-section-head">
                <Target size={18} />
                <h2>趋势预测</h2>
                <span className="pred-section-count">{predictions.length}</span>
              </div>
              {predictions.length === 0 ? (
                <div className="pred-empty">
                  暂无趋势预测。预测基于信号聚类生成，需 prediction loop generate 阶段成功产出。
                </div>
              ) : (
                <div className="pred-list">
                  {predictions.map((pred) => (
                    <div
                      key={pred.id}
                      className={`pred-prediction-card${expandedPrediction === pred.id ? ' expanded' : ''}`}
                      onClick={() => setExpandedPrediction(expandedPrediction === pred.id ? null : pred.id)}
                    >
                      <div className="pred-prediction-head">
                        <div className="pred-prediction-title-row">
                          {pred.status === 'pending' ? (
                            <Clock size={14} style={{ color: '#fbbf24', flexShrink: 0 }} />
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
                          {pred.confidence != null && (
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
                      <div className="pred-review-head">
                        <div className="pred-review-score" style={{ color: HIT_LEVEL_COLORS[review.hit_level] || '#8aa3be' }}>
                          <strong>{review.score}</strong>/5
                        </div>
                        <span className="pred-badge" style={{ color: HIT_LEVEL_COLORS[review.hit_level] }}>
                          {review.hit_level}
                        </span>
                        <span className="pred-badge pred-badge-muted">{review.prediction_status}</span>
                      </div>
                      <h3 className="pred-review-title">{review.prediction_title}</h3>
                      {review.cluster_label && (
                        <span className="pred-badge pred-badge-accent" style={{ marginBottom: 8 }}>
                          {review.cluster_label}
                        </span>
                      )}
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
                  ))}
                </div>
              )}
            </section>
          </div>
        </div>
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
          <h1 className="h1">预测循环</h1>
        </div>
        <div className="muted dashboard-updated">
          Signal Cluster → Trend Prediction → Prediction Review
        </div>
      </div>
    </div>
  )
}
