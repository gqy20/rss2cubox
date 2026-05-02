'use client'

import React from 'react'
import { ExternalLink } from 'lucide-react'
import MarkdownRenderer from './MarkdownRenderer'
import { SourceLogo, formatRelativeTime, formatShortTime, hasAiSummary } from './utils'
import type { Row } from './types'

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
  1: '天级',
  2: '周级',
  3: '月级',
  4: '季度',
  5: '年级',
}

function getSignalTypeLabel(value: unknown): string {
  return typeof value === 'number' ? SIGNAL_TYPE_LABELS[value] || '' : ''
}

function getImpactHorizonLabel(value: unknown): string {
  return typeof value === 'number' ? IMPACT_HORIZON_LABELS[value] || '' : ''
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
  const evidenceStrength = boundedScore(row.evidence_strength)
  const noveltyScore = boundedScore(row.novelty_score)
  const confidence = boundedScore(row.confidence)
  const impactHorizonLabel = getImpactHorizonLabel(row.impact_horizon)
  const entities = Array.isArray(row.entities) ? row.entities.filter(Boolean).slice(0, 3) : []
  const watchKeywords = Array.isArray(row.watch_keywords) ? row.watch_keywords.filter(Boolean).slice(0, 3) : []
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

  void groupId
  void idx

  return (
    <div className="timeline-item">
      <article
        className={`timeline-content timeline-compact${hasSummary ? ' timeline-high' : ''}${isHovered ? ' hover-open' : ''}`}
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
        {/* Row 1: source + time + actions */}
        <div className="t-header" style={{ marginBottom: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
            <SourceLogo row={row} />
            <span style={{ fontSize: 11, color: '#8aa3be', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {row.source}
            </span>
            {row.enriched && (
              <span className="enriched-badge">ENR</span>
            )}
            {importanceScore && (
              <span className={`importance-badge score-${importanceScore}`}>
                S{importanceScore}
              </span>
            )}
            {signalTypeLabel && (
              <span style={{ fontSize: 10, color: '#6b7e94', whiteSpace: 'nowrap' }}>
                {signalTypeLabel}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div className={`node-dot${hasSummary ? ' glow-green' : ' glow-gray'}`} />
            <span suppressHydrationWarning className="node-time">
              {formatRelativeTime(row.time, now)}
            </span>
            <a href={row.url} target="_blank" rel="noreferrer" aria-label="打开原文" style={{ display: 'inline-flex', alignItems: 'center' }} onClick={(e) => e.stopPropagation()}>
              <ExternalLink size={12} color="#6b7e94" />
            </a>
          </div>
        </div>

        {/* Row 2: title */}
        <a href={row.url} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }} onClick={(e) => e.stopPropagation()}>
          <h3 className="t-title">{row.title || row.hidden_signal || '未命名信号'}</h3>
        </a>

        {/* Tags row (compact) */}
        {row.tags && row.tags.length > 0 && (
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 3 }}>
            {row.tags.slice(0, 2).map((tag, i) => (
              <span
                key={i}
                className={`hashtag${selectedTag === tag ? ' hashtag-active' : ''}`}
                style={{ fontSize: 10, padding: '1px 5px' }}
                onClick={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  onTagClick(tag)
                }}
              >
                #{tag}
              </span>
            ))}
            {hasExpandableContent && (
              <span style={{ fontSize: 10, color: '#4b5e73', marginLeft: 2 }}>
                {isHovered ? '收起' : '···'}
              </span>
            )}
          </div>
        )}

        {/* Expanded AI content */}
        <div className={`t-ai-content${isHovered ? ' expanded' : ''}`}>
          {(evidenceStrength || noveltyScore || confidence || impactHorizonLabel) && (
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 6, marginTop: 6 }}>
              {evidenceStrength && <span className="hashtag" style={{ fontSize: 10 }}>证据 {evidenceStrength}</span>}
              {noveltyScore && <span className="hashtag" style={{ fontSize: 10 }}>新颖 {noveltyScore}</span>}
              {confidence && <span className="hashtag" style={{ fontSize: 10 }}>置信 {confidence}</span>}
              {impactHorizonLabel && <span className="hashtag" style={{ fontSize: 10 }}>{impactHorizonLabel}</span>}
            </div>
          )}
          {row.core_event && (
            <div className="t-ai-box" style={{ padding: 8, marginBottom: 6, background: 'rgba(52, 211, 153, 0.04)', borderLeft: '2px solid #34d399', borderRadius: '0 4px 4px 0' }}>
              <span style={{ fontSize: 12, color: '#34d399', fontWeight: 700, marginRight: 4 }}>核心</span>
              <MarkdownRenderer inline>{row.core_event}</MarkdownRenderer>
            </div>
          )}
          {row.actionable && (
            <div className="t-ai-box" style={{ padding: 8, background: 'rgba(250, 204, 21, 0.04)', borderLeft: '2px solid #facc15', borderRadius: '0 4px 4px 0', marginBottom: row.reason ? 6 : 0 }}>
              <span style={{ fontSize: 12, color: '#facc15', fontWeight: 700, marginRight: 4 }}>建议</span>
              <MarkdownRenderer inline>{row.actionable}</MarkdownRenderer>
            </div>
          )}
          {row.reason && (
            <div className="t-ai-box" style={{ padding: 8, background: 'rgba(96, 165, 250, 0.04)', borderLeft: '2px solid #60a5fa', borderRadius: '0 4px 4px 0' }}>
              <span style={{ fontSize: 12, color: '#60a5fa', fontWeight: 700, marginRight: 4 }}>分析</span>
              <MarkdownRenderer inline>{row.reason}</MarkdownRenderer>
            </div>
          )}
          {entities.length > 0 && (
            <div className="signal-meta-group" style={{ marginTop: 4 }}>
              <strong className="signal-meta-label">实体</strong>
              <div className="signal-meta-list">
                {entities.map((entity) => (
                  <span key={entity} className="hashtag" style={{ fontSize: 10 }}>
                    {String(entity).trim()}
                  </span>
                ))}
              </div>
            </div>
          )}
          {watchKeywords.length > 0 && (
            <div className="signal-meta-group" style={{ marginTop: 4 }}>
              <strong className="signal-meta-label">追踪</strong>
              <div className="signal-meta-list">
                {watchKeywords.map((kw) => (
                  <span key={kw} className="hashtag" style={{ fontSize: 10 }}>
                    {String(kw).trim()}
                  </span>
                ))}
              </div>
            </div>
          )}
          {row.prediction && (
            <div className="t-ai-box" style={{ padding: 8, marginTop: 6, background: 'rgba(167, 139, 250, 0.04)', borderLeft: '2px solid #a78bfa', borderRadius: '0 4px 4px 0' }}>
              <span style={{ fontSize: 12, color: '#a78bfa', fontWeight: 700, marginRight: 4 }}>观察</span>
              <MarkdownRenderer inline>{row.prediction}</MarkdownRenderer>
            </div>
          )}
        </div>
      </article>
    </div>
  )
})

export default FeedCard
