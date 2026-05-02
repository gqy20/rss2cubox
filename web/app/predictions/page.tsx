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
  new: '#60a5fa',
  warming: '#fbbf24',
  bursting: '#f87171',
  mature: '#a78bfa',
  declining: '#6b7280',
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

export default function PredictionsPage() {
  const [clusters, setClusters] = useState<SignalCluster[]>([])
  const [predictions, setPredictions] = useState<TrendPrediction[]>([])
  const [reviews, setReviews] = useState<PredictionReview[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedCluster, setExpandedCluster] = useState<number | null>(null)
  const [expandedPrediction, setExpandedPrediction] = useState<number | null>(null)

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

  if (loading) {
    return (
      <main className="main">
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
      <main className="main">
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

  const statusStats = clusters.reduce(
    (acc, c) => {
      acc[c.status] = (acc[c.status] || 0) + 1
      return acc
    },
    {} as Record<string, number>,
  )

  return (
    <main className="main">
      <div className="predictions-page">
        <PredictionsHeader />

        <div className="predictions-kpi-row">
          <div className="glass predictions-kpi-card">
            <Sparkles size={16} />
            <div className="predictions-kpi-value">{clusters.length}</div>
            <div className="predictions-kpi-label">信号聚类</div>
            <div className="predictions-kpi-detail">
              {Object.entries(statusStats).map(([status, count]) => (
                <span key={status} style={{ color: STATUS_COLORS[status] || '#8aa3be' }}>
                  {status} {count}
                </span>
              ))}
            </div>
          </div>
          <div className="glass predictions-kpi-card">
            <Target size={16} />
            <div className="predictions-kpi-value">{predictions.length}</div>
            <div className="predictions-kpi-label">趋势预测</div>
            <div className="predictions-kpi-detail">
              {predictions.length > 0
                ? `${predictions.filter((p) => p.status === 'pending').length} 待验证 / ${predictions.filter((p) => p.status !== 'pending').length} 已完成`
                : '暂无数据'}
            </div>
          </div>
          <div className="glass predictions-kpi-card">
            <BarChart3 size={16} />
            <div className="predictions-kpi-value">{reviews.length}</div>
            <div className="predictions-kpi-label">预测复盘</div>
            <div className="predictions-kpi-detail">
              {reviews.length > 0
                ? `平均分 ${(reviews.reduce((s, r) => s + r.score, 0) / reviews.length).toFixed(1)}`
                : '暂无数据'}
            </div>
          </div>
        </div>

        <section className="predictions-section">
          <div className="predictions-section-head">
            <Brain size={18} />
            <h2>信号聚类</h2>
            <span className="predictions-section-count">{clusters.length}</span>
          </div>
          {clusters.length === 0 ? (
            <div className="predictions-empty">暂无信号聚类数据，等待 prediction loop cluster 阶段产出。</div>
          ) : (
            <div className="predictions-cluster-grid">
              {clusters.map((cluster) => (
                <div
                  key={cluster.id}
                  className="glass predictions-cluster-card"
                  onClick={() => setExpandedCluster(expandedCluster === cluster.id ? null : cluster.id)}
                >
                  <div className="predictions-cluster-head">
                    <div className="predictions-cluster-title-row">
                      <span
                        className="predictions-cluster-status"
                        style={{ background: STATUS_COLORS[cluster.status] || '#6b7280' }}
                      />
                      <h3>{cluster.label}</h3>
                    </div>
                    <div className="predictions-cluster-meta">
                      {cluster.signal_type && (
                        <span className="predictions-badge">{SIGNAL_TYPE_MAP[cluster.signal_type] || `类型${cluster.signal_type}`}</span>
                      )}
                      <span className="predictions-badge predictions-badge-muted">{cluster.status}</span>
                      <span className="predictions-badge predictions-badge-muted">
                        <Tag size={10} /> {cluster.article_count} 篇
                      </span>
                    </div>
                  </div>
                  {cluster.summary && <p className="predictions-cluster-summary">{cluster.summary}</p>}
                  <div className="predictions-cluster-footer">
                    {cluster.entities && cluster.entities.length > 0 && (
                      <div className="predictions-tags">
                        {cluster.entities.slice(0, 5).map((e, i) => (
                          <span key={i} className="predictions-tag predictions-tag-entity">{e}</span>
                        ))}
                        {cluster.entities.length > 5 && <span className="predictions-tag">+{cluster.entities.length - 5}</span>}
                      </div>
                    )}
                    <span className="predictions-time-muted">
                      更新 {formatDate(cluster.updated_at)}
                    </span>
                  </div>
                  {expandedCluster === cluster.id && (
                    <div className="predictions-cluster-expanded">
                      {cluster.watch_keywords && cluster.watch_keywords.length > 0 && (
                        <div className="predictions-expanded-row">
                          <span className="predictions-expanded-label">监控关键词</span>
                          <div className="predictions-tags">
                            {cluster.watch_keywords.map((kw, i) => (
                              <span key={i} className="predictions-tag predictions-tag-keyword">{kw}</span>
                            ))}
                          </div>
                        </div>
                      )}
                      <div className="predictions-expanded-row">
                        <span className="predictions-expanded-label">评分</span>
                        <div className="predictions-scores">
                          {cluster.avg_importance != null && (
                            <span>重要性 <strong>{Number(cluster.avg_importance).toFixed(1)}</strong></span>
                          )}
                          {cluster.avg_confidence != null && (
                            <span>置信度 <strong>{Number(cluster.avg_confidence).toFixed(1)}</strong></span>
                          )}
                          {cluster.source_count > 0 && <span>来源 <strong>{cluster.source_count}</strong></span>}
                        </div>
                      </div>
                      {cluster.first_seen_at && (
                        <div className="predictions-expanded-row">
                          <span className="predictions-expanded-label">时间窗口</span>
                          <span className="predictions-time-muted">
                            {formatDateShort(cluster.first_seen_at)} ~ {formatDateShort(cluster.last_seen_at)}
                          </span>
                        </div>
                      )}
                      {cluster.linked_articles && cluster.linked_articles.length > 0 && (
                        <div className="predictions-expanded-row">
                          <span className="predictions-expanded-label">关联文章</span>
                          <span className="predictions-time-muted">{cluster.linked_articles.length} 篇</span>
                        </div>
                      )}
                    </div>
                  )}
                  <div className="predictions-expand-hint">
                    {expandedCluster === cluster.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="predictions-section">
          <div className="predictions-section-head">
            <TrendingUp size={18} />
            <h2>趋势预测</h2>
            <span className="predictions-section-count">{predictions.length}</span>
          </div>
          {predictions.length === 0 ? (
            <div className="predictions-empty">
              暂无趋势预测。预测基于信号聚类生成，需 prediction loop generate 阶段成功产出。
            </div>
          ) : (
            <div className="predictions-list">
              {predictions.map((pred) => (
                <div
                  key={pred.id}
                  className="glass predictions-prediction-card"
                  onClick={() => setExpandedPrediction(expandedPrediction === pred.id ? null : pred.id)}
                >
                  <div className="predictions-prediction-head">
                    <div className="predictions-prediction-title-row">
                      {pred.status === 'pending' ? (
                        <Clock size={14} style={{ color: '#fbbf24', flexShrink: 0 }} />
                      ) : pred.status === 'hit' ? (
                        <CheckCircle2 size={14} style={{ color: '#34d399', flexShrink: 0 }} />
                      ) : (
                        <XCircle size={14} style={{ color: '#ef4444', flexShrink: 0 }} />
                      )}
                      <h3>{pred.prediction_title}</h3>
                    </div>
                    <div className="predictions-prediction-meta">
                      {pred.prediction_type && (
                        <span className="predictions-badge">{PREDICTION_TYPE_MAP[pred.prediction_type] || `类型${pred.prediction_type}`}</span>
                      )}
                      <span className="predictions-badge predictions-badge-muted">{pred.status}</span>
                      {pred.confidence != null && (
                        <span className="predictions-badge predictions-badge-muted">置信度 {pred.confidence}/5</span>
                      )}
                      {pred.cluster_label && (
                        <span className="predictions-badge predictions-badge-accent">{pred.cluster_label}</span>
                      )}
                    </div>
                  </div>
                  <p className="predictions-prediction-body">{pred.prediction_body}</p>
                  <div className="predictions-prediction-footer">
                    <span className="predictions-time-muted">
                      目标窗口 {formatDateShort(pred.target_start_at)} ~ {formatDateShort(pred.target_end_at)}（{pred.horizon_days}天）
                    </span>
                    <span className="predictions-time-muted">创建于 {formatDate(pred.created_at)}</span>
                  </div>
                  {expandedPrediction === pred.id && (
                    <div className="predictions-cluster-expanded">
                      {pred.watch_keywords && pred.watch_keywords.length > 0 && (
                        <div className="predictions-expanded-row">
                          <span className="predictions-expanded-label">监控关键词</span>
                          <div className="predictions-tags">
                            {pred.watch_keywords.map((kw, i) => (
                              <span key={i} className="predictions-tag predictions-tag-keyword">{kw}</span>
                            ))}
                          </div>
                        </div>
                      )}
                      {pred.expected_evidence && Object.keys(pred.expected_evidence).length > 0 && (
                        <div className="predictions-expanded-row">
                          <span className="predictions-expanded-label">预期证据</span>
                          <pre className="predictions-json">{JSON.stringify(pred.expected_evidence, null, 2)}</pre>
                        </div>
                      )}
                      {pred.disconfirming_evidence && (
                        <div className="predictions-expanded-row">
                          <span className="predictions-expanded-label">证伪标准</span>
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

        <section className="predictions-section">
          <div className="predictions-section-head">
            <BarChart3 size={18} />
            <h2>预测复盘</h2>
            <span className="predictions-section-count">{reviews.length}</span>
          </div>
          {reviews.length === 0 ? (
            <div className="predictions-empty">
              暂无预测复盘数据。复盘在预测窗口结束后自动执行，需 prediction loop review 阶段产出。
            </div>
          ) : (
            <div className="predictions-list">
              {reviews.map((review) => (
                <div key={review.id} className="glass predictions-review-card">
                  <div className="predictions-review-head">
                    <div className="predictions-review-score" style={{ color: HIT_LEVEL_COLORS[review.hit_level] || '#8aa3be' }}>
                      <strong>{review.score}</strong>/5
                    </div>
                    <span className="predictions-badge" style={{ color: HIT_LEVEL_COLORS[review.hit_level] }}>
                      {review.hit_level}
                    </span>
                    <span className="predictions-badge predictions-badge-muted">{review.prediction_status}</span>
                  </div>
                  <h3 className="predictions-review-title">{review.prediction_title}</h3>
                  {review.cluster_label && (
                    <span className="predictions-badge predictions-badge-accent" style={{ marginBottom: 8 }}>
                      {review.cluster_label}
                    </span>
                  )}
                  {review.actual_observation && (
                    <div className="predictions-review-field">
                      <span className="predictions-review-label">实际观察</span>
                      <p>{review.actual_observation}</p>
                    </div>
                  )}
                  {review.why_score && (
                    <div className="predictions-review-field">
                      <span className="predictions-review-label">评分理由</span>
                      <p>{review.why_score}</p>
                    </div>
                  )}
                  {review.improvement_advice && (
                    <div className="predictions-review-field">
                      <span className="predictions-review-label">改进建议</span>
                      <p>{review.improvement_advice}</p>
                    </div>
                  )}
                  <div className="predictions-review-footer">
                    {review.supporting_articles && review.supporting_articles.length > 0 && (
                      <span className="predictions-time-muted">支持 {review.supporting_articles.length} 篇</span>
                    )}
                    {review.contradicting_articles && review.contradicting_articles.length > 0 && (
                      <span className="predictions-time-muted">矛盾 {review.contradicting_articles.length} 篇</span>
                    )}
                    <span className="predictions-time-muted">复盘于 {formatDate(review.reviewed_at)}</span>
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
          <h1 className="h1">预测循环</h1>
        </div>
        <div className="muted dashboard-updated">
          Signal Cluster → Trend Prediction → Prediction Review
        </div>
      </div>
    </div>
  )
}
