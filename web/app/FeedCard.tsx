'use client'

import React from 'react'
import { ExternalLink } from 'lucide-react'
import MarkdownRenderer from './MarkdownRenderer'
import { SourceLogo, formatRelativeTime, hasAiSummary } from './utils'
import type { Row } from './types'

function extractBvid(value: string): string {
  const text = String(value || '')
  const match = text.match(/BV[A-Za-z0-9]{8,}/i)
  return match ? match[0] : ''
}

function clampScore(value: unknown, min = 1, max = 5): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  const score = Math.round(value)
  return score >= min && score <= max ? score : null
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
  idx?: number
  groupId?: string
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
  const importanceScore = clampScore(row.importance_score)
  const signalTypeLabel = getSignalTypeLabel(row.signal_type)
  const contentSourceLabel = getContentSourceLabel(row.content_source)
  const evidenceStrength = clampScore(row.evidence_strength)
  const noveltyScore = clampScore(row.novelty_score)
  const confidence = clampScore(row.confidence)
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
  const isYoutubeRow = /youtube\.com\/watch|youtu\.be\//i.test(row.url || '')
  const isBiliRow = /(?:bilibili\.com|b23\.tv)\//i.test(row.url || '')
  const bvid = extractBvid(row.url || '')
  const directCoverUrl = String(row.cover_url || '').replace(/^http:\/\//i, 'https://')
  const proxyCoverUrl = bvid
    ? `/api/bili-cover?bvid=${encodeURIComponent(bvid)}${directCoverUrl ? `&pic=${encodeURIComponent(directCoverUrl)}` : ''}`
    : ''
  const coverUrl = isBiliRow ? (proxyCoverUrl || directCoverUrl) : (directCoverUrl || proxyCoverUrl)
  const hasCover = Boolean(coverUrl) && (
    isYoutubeRow || isBiliRow ||
    /^\/api\/bili-cover\?/i.test(coverUrl) ||
    /ytimg\.com\//i.test(coverUrl) ||
    /hdslb\.com\//i.test(coverUrl)
  )

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
        <div className="t-header">
          <div className="t-source-row">
            <SourceLogo row={row} />
            <span className="t-source-name">{row.source}</span>
            {row.enriched && (
              <span className="enriched-badge">ENR</span>
            )}
            {row.full_text && (
              <span className="ft-badge" title={`全文 · ${row.full_text_source || '未知来源'}`}>FT</span>
            )}
            {contentSourceLabel && (
              <span className="content-source-badge" title="分析来源">{contentSourceLabel}</span>
            )}
            {importanceScore && (
              <span className={`importance-badge score-${importanceScore}`}>
                S{importanceScore}
              </span>
            )}
            {signalTypeLabel && (
              <span className="t-signal-type">{signalTypeLabel}</span>
            )}
          </div>
          <div className="t-meta-row">
            <div className={`node-dot${hasSummary ? ' glow-green' : ' glow-gray'}`} />
            <span suppressHydrationWarning className="node-time">
              {formatRelativeTime(row.time, now)}
            </span>
            <a href={row.url} target="_blank" rel="noreferrer" aria-label="打开原文" className="t-external-link" onClick={(e) => e.stopPropagation()}>
              <ExternalLink size={12} color="#6b7e94" />
            </a>
          </div>
        </div>

        {/* Row 2: title */}
        <a href={row.url} target="_blank" rel="noreferrer" className="t-title-link" onClick={(e) => e.stopPropagation()}>
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
              referrerPolicy={isBiliRow ? 'no-referrer' : undefined}
              onError={(e) => {
                const current = e.currentTarget.getAttribute('src') || ''
                if (!isBiliRow && proxyCoverUrl && current !== proxyCoverUrl) {
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

        {/* Tags row (compact) */}
        {(row.tags && row.tags.length > 0) || hasExpandableContent ? (
          <div className="t-tags-row">
            {row.tags?.slice(0, 2).map((tag, i) => (
              <span
                key={i}
                className={`hashtag t-meta-tag${selectedTag === tag ? ' hashtag-active' : ''}`}
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
              <span className="t-expand-hint-text">
                {isHovered ? '收起详情' : '查看详情'}
              </span>
            )}
          </div>
        ) : null}

        {/* Expanded AI content */}
        <div className={`t-ai-content${isHovered ? ' expanded' : ''}`}>
          {(evidenceStrength || noveltyScore || confidence || impactHorizonLabel) && (
            <div className="t-meta-tags">
              {evidenceStrength && <span className="hashtag t-meta-tag">证据 {evidenceStrength}/5</span>}
              {noveltyScore && <span className="hashtag t-meta-tag">新颖 {noveltyScore}/5</span>}
              {confidence && confidence >= 2 && <span className="hashtag t-meta-tag">置信 {confidence}/5</span>}
              {impactHorizonLabel && <span className="hashtag t-meta-tag">{impactHorizonLabel}</span>}
            </div>
          )}
          {row.core_event && (
            <div className="t-ai-core">
              <span className="t-ai-label t-ai-label-core">核心</span>
              <MarkdownRenderer inline>{row.core_event}</MarkdownRenderer>
            </div>
          )}
          {row.actionable && (
            <div className={`t-ai-action${row.reason ? '' : ' t-ai-box-last'}`}>
              <span className="t-ai-label t-ai-label-action">建议</span>
              <MarkdownRenderer inline>{row.actionable}</MarkdownRenderer>
            </div>
          )}
          {row.reason && (
            <div className="t-ai-reason">
              <span className="t-ai-label t-ai-label-reason">分析</span>
              <MarkdownRenderer inline>{row.reason}</MarkdownRenderer>
            </div>
          )}
          {entities.length > 0 && (
            <div className="signal-meta-group">
              <strong className="signal-meta-label">实体</strong>
              <div className="signal-meta-list">
                {entities.map((entity) => (
                  <span key={entity} className="hashtag t-meta-tag">
                    {String(entity).trim()}
                  </span>
                ))}
              </div>
            </div>
          )}
          {watchKeywords.length > 0 && (
            <div className="signal-meta-group">
              <strong className="signal-meta-label">追踪</strong>
              <div className="signal-meta-list">
                {watchKeywords.map((kw) => (
                  <span key={kw} className="hashtag t-meta-tag">
                    {String(kw).trim()}
                  </span>
                ))}
              </div>
            </div>
          )}
          {row.prediction && (
            <div className="t-ai-predict">
              <span className="t-ai-label t-ai-label-predict">观察</span>
              <MarkdownRenderer inline>{row.prediction}</MarkdownRenderer>
            </div>
          )}
        </div>
      </article>
    </div>
  )
})

export default FeedCard
