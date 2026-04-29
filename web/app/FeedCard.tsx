'use client'

import React from 'react'
import { ExternalLink } from 'lucide-react'
import { SourceLogo, formatRelativeTime, formatShortTime, hasAiSummary } from './utils'
import type { Row } from './types'

function extractBvid(value: string): string {
  const text = String(value || '')
  const match = text.match(/BV[A-Za-z0-9]{8,}/i)
  return match ? match[0].toUpperCase() : ''
}

function getImportanceScore(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  const score = Math.round(value)
  return score >= 1 && score <= 5 ? score : null
}

function boundedScore(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  const score = Math.round(value)
  return score >= 1 && score <= 5 ? score : null
}

const SIGNAL_TYPE_LABELS: Record<number, string> = {
  1: '模型能力',
  2: '基础设施',
  3: '开发者工作流',
  4: '产品应用',
  5: '开源生态',
  6: '研究算法',
  7: '安全风险',
  8: '监管政策',
  9: '商业组织',
  10: '数据评测',
  11: '具身智能',
  12: '其他',
}

const IMPACT_HORIZON_LABELS: Record<number, string> = {
  1: '天级影响',
  2: '周级影响',
  3: '月级影响',
  4: '季度影响',
  5: '年级影响',
}

function getSignalTypeLabel(value: unknown): string {
  return typeof value === 'number' ? SIGNAL_TYPE_LABELS[value] || '' : ''
}

function getImpactHorizonLabel(value: unknown): string {
  return typeof value === 'number' ? IMPACT_HORIZON_LABELS[value] || '' : ''
}

function getContentSourceLabel(value: unknown): string {
  if (value === 'full_text') return '全文'
  if (value === 'summary_only') return '摘要'
  return ''
}

type FeedCardProps = {
  row: Row
  idx: number
  groupId: string
  now: Date | null
  hoveredRowKey: string | null
  selectedTag: string | null
  onHoverEnter: (key: string) => void
  onHoverLeave: (key: string) => void
  onToggleOpen: (key: string) => void
  onTagClick: (tag: string) => void
}

const FeedCard = React.memo(function FeedCard({
  row,
  idx,
  groupId,
  now,
  hoveredRowKey,
  selectedTag,
  onHoverEnter,
  onHoverLeave,
  onToggleOpen,
  onTagClick,
}: FeedCardProps) {
  const hasSummary = hasAiSummary(row)
  const rowKey = row.id || `${row.url}|${row.time}|${row.title || 'untitled'}`
  const isHovered = hoveredRowKey === rowKey
  const importanceScore = getImportanceScore(row.importance_score)
  const signalTypeLabel = getSignalTypeLabel(row.signal_type)
  const contentSourceLabel = getContentSourceLabel(row.content_source)
  const evidenceStrength = boundedScore(row.evidence_strength)
  const noveltyScore = boundedScore(row.novelty_score)
  const confidence = boundedScore(row.confidence)
  const impactHorizonLabel = getImpactHorizonLabel(row.impact_horizon)
  const entities = Array.isArray(row.entities) ? row.entities.filter(Boolean).slice(0, 4) : []
  const watchKeywords = Array.isArray(row.watch_keywords) ? row.watch_keywords.filter(Boolean).slice(0, 4) : []
  const hasPrimaryAiContent = Boolean(row.core_event || row.actionable || row.reason)
  const hasSignalMetadata = Boolean(
    evidenceStrength ||
    noveltyScore ||
    confidence ||
    impactHorizonLabel ||
    entities.length > 0 ||
    watchKeywords.length > 0 ||
    row.prediction,
  )
  const hasExpandableContent = hasPrimaryAiContent || hasSignalMetadata
  const isYoutubeRow = /youtube\.com\/watch|youtu\.be\//i.test(row.url || '')
  const isBiliRow = /(?:bilibili\.com|b23\.tv)\//i.test(row.url || '')
  const bvid = extractBvid(row.url || '')
  const directCoverUrl = String(row.cover_url || '').replace(/^http:\/\//i, 'https://')
  // Keep old stable priority: direct cover first, proxy only when missing.
  const proxyCoverUrl = bvid ? `/api/bili-cover?bvid=${encodeURIComponent(bvid)}` : ''
  const coverUrl = directCoverUrl || proxyCoverUrl
  const hasCover = Boolean(coverUrl) && (
    isYoutubeRow || isBiliRow ||
    /^\/api\/bili-cover\?/i.test(coverUrl) ||
    /ytimg\.com\//i.test(coverUrl) ||
    /hdslb\.com\//i.test(coverUrl)
  )

  // suppress unused groupId lint warning — used externally as key
  void groupId

  return (
    <div className="timeline-item timeline-item-enter" style={{ animationDelay: `${Math.min(idx * 0.02, 0.15)}s` }}>
      <article
        className={`glass timeline-content timeline-compact${hasSummary ? ' timeline-high' : ''}${isHovered ? ' hover-open' : ''}`}
        onMouseEnter={() => onHoverEnter(rowKey)}
        onMouseLeave={() => onHoverLeave(rowKey)}
        onClick={() => {
          if (hasExpandableContent) onToggleOpen(rowKey)
        }}
        onKeyDown={(e) => {
          if (!hasExpandableContent) return
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onToggleOpen(rowKey)
          }
        }}
        role={hasExpandableContent ? 'button' : undefined}
        tabIndex={hasExpandableContent ? 0 : undefined}
        aria-expanded={hasExpandableContent ? isHovered : undefined}
      >
        <div className="t-header" style={{ marginBottom: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
            <span className="source-badge" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <SourceLogo row={row} />
              {row.source}
            </span>
            {row.enriched && (
              <span className="enriched-badge" title="已完成全文深化分析">
                Enriched
              </span>
            )}
            {importanceScore && (
              <span
                className={`importance-badge score-${importanceScore}`}
                title={`重要度 ${importanceScore}/5`}
                aria-label={`重要度 ${importanceScore}/5`}
              >
                S{importanceScore}
              </span>
            )}
            {signalTypeLabel && (
              <span className="enriched-badge" title="信号类型">
                {signalTypeLabel}
              </span>
            )}
            {contentSourceLabel && (
              <span className="enriched-badge" title="分析来源">
                {contentSourceLabel}
              </span>
            )}
            <span suppressHydrationWarning className="node-time" title={`${row.time} ${formatShortTime(row.time)}`}>
              {formatRelativeTime(row.time, now)}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div className={`node-dot ${hasSummary ? 'glow-green' : 'glow-gray'}`} />
            <a href={row.url} target="_blank" rel="noreferrer" aria-label="打开原文" style={{ display: 'inline-flex', alignItems: 'center' }} onClick={(e) => e.stopPropagation()}>
              <ExternalLink size={13} color="#8aa3be" />
            </a>
          </div>
        </div>

        <a href={row.url} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }} onClick={(e) => e.stopPropagation()}>
          <h3 className="t-title">{row.title || row.hidden_signal || '未命名信号'}</h3>
        </a>

        {hasCover && (
          <a href={row.url} target="_blank" rel="noreferrer" className="t-cover-wrap" aria-label="打开原文封面" onClick={(e) => e.stopPropagation()}>
            <img
              className="t-cover"
              src={coverUrl}
              alt={row.title || '封面图'}
              loading="lazy"
              width={480}
              height={270}
              onError={(e) => {
                // Fallback to proxy when direct cover fails (e.g. anti-hotlink), and vice versa.
                const current = e.currentTarget.getAttribute('src') || ''
                if (proxyCoverUrl && current !== proxyCoverUrl) {
                  e.currentTarget.setAttribute('src', proxyCoverUrl)
                  return
                }
                if (directCoverUrl && current !== directCoverUrl) {
                  e.currentTarget.setAttribute('src', directCoverUrl)
                }
              }}
            />
          </a>
        )}

        {row.tags && row.tags.length > 0 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6 }}>
            {row.tags.slice(0, 3).map((tag, i) => (
              <span
                key={i}
                className={`hashtag${selectedTag === tag ? ' hashtag-active' : ''}`}
                onClick={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  onTagClick(tag)
                }}
              >
                #{tag}
              </span>
            ))}
          </div>
        )}

        {!hasPrimaryAiContent && (row.hidden_signal || row.core_event || row.actionable) && (
          <p className="t-reason-preview t-reason-single" style={{ margin: 0 }}>
            {row.hidden_signal || row.core_event || row.actionable}
          </p>
        )}

        {hasExpandableContent && (
          <p className="t-expand-hint">
            {isHovered ? '收起详情' : hasPrimaryAiContent ? '点击查看 AI 分析' : '点击查看信号元数据'}
          </p>
        )}

        <div className={`t-ai-content${isHovered ? ' expanded' : ''}`}>
          {(evidenceStrength || noveltyScore || confidence || impactHorizonLabel) && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
              {evidenceStrength && <span className="hashtag">证据 {evidenceStrength}/5</span>}
              {noveltyScore && <span className="hashtag">新颖 {noveltyScore}/5</span>}
              {confidence && <span className="hashtag">置信 {confidence}/5</span>}
              {impactHorizonLabel && <span className="hashtag">{impactHorizonLabel}</span>}
            </div>
          )}
          {row.core_event && (
            <div className="t-ai-box" style={{ padding: 10, marginBottom: 8, background: 'rgba(52, 211, 153, 0.04)', borderLeft: '2px solid #34d399', borderRadius: '0 4px 4px 0' }}>
              <p className="ai-text" style={{ fontSize: 13, color: '#e2e8f0', margin: 0 }}>
                <strong style={{ color: '#34d399', marginRight: 6 }}>核心</strong>
                {row.core_event}
              </p>
            </div>
          )}
          {row.actionable && (
            <div className="t-ai-box" style={{ padding: 10, background: 'rgba(250, 204, 21, 0.04)', borderLeft: '2px solid #facc15', borderRadius: '0 4px 4px 0', marginBottom: row.reason ? 8 : 0 }}>
              <p className="ai-text" style={{ fontSize: 13, color: '#e2e8f0', margin: 0 }}>
                <strong style={{ color: '#facc15', marginRight: 6 }}>建议</strong>
                {row.actionable}
              </p>
            </div>
          )}
          {row.reason && (
            <div className="t-ai-box" style={{ padding: 10, background: 'rgba(96, 165, 250, 0.04)', borderLeft: '2px solid #60a5fa', borderRadius: '0 4px 4px 0' }}>
              <p className="ai-text" style={{ fontSize: 13, color: '#e2e8f0', margin: 0 }}>
                <strong style={{ color: '#60a5fa', marginRight: 6 }}>分析</strong>
                {row.reason}
              </p>
            </div>
          )}
          {entities.length > 0 && (
            <div className="signal-meta-group">
              <strong className="signal-meta-label">实体</strong>
              <div className="signal-meta-list">
                {entities.map((entity) => <span key={entity} className="hashtag">{entity}</span>)}
              </div>
            </div>
          )}
          {watchKeywords.length > 0 && (
            <div className="signal-meta-group">
              <strong className="signal-meta-label">追踪</strong>
              <div className="signal-meta-list">
                {watchKeywords.map((keyword) => <span key={keyword} className="hashtag">{keyword}</span>)}
              </div>
            </div>
          )}
          {row.prediction && (
            <div className="t-ai-box" style={{ padding: 10, marginTop: 8, background: 'rgba(167, 139, 250, 0.04)', borderLeft: '2px solid #a78bfa', borderRadius: '0 4px 4px 0' }}>
              <p className="ai-text" style={{ fontSize: 13, color: '#e2e8f0', margin: 0 }}>
                <strong style={{ color: '#a78bfa', marginRight: 6 }}>后续观察</strong>
                {row.prediction}
              </p>
            </div>
          )}
        </div>
      </article>
    </div>
  )
})

export default FeedCard
