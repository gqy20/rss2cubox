'use client'

import React from 'react'
import { ExternalLink } from 'lucide-react'
import { motion, useReducedMotion } from 'framer-motion'
import { SourceLogo, ScoreBar, formatRelativeTime, formatShortTime } from './utils'
import type { Row } from './types'

type FeedCardProps = {
  row: Row
  idx: number
  groupId: string
  now: Date | null
  hoveredRowKey: string | null
  selectedTag: string | null
  onHoverEnter: (key: string) => void
  onHoverLeave: (key: string) => void
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
  onTagClick,
}: FeedCardProps) {
  const s = row.score ?? 0
  const isHigh = s >= 0.85
  const isMid = s >= 0.7 && s < 0.85
  const rowKey = row.id || `${row.url}|${row.time}|${row.title || 'untitled'}`
  const isHovered = hoveredRowKey === rowKey
  const hasAiContent = Boolean(row.core_event || row.actionable || row.reason)
  const isYoutubeRow = /youtube\.com\/watch|youtu\.be\//i.test(row.url || '')
  const isBiliRow = /bilibili\.com\/video\//i.test(row.url || '')
  const bvMatch = isBiliRow ? /bilibili\.com\/video\/(BV[A-Za-z0-9]+)/i.exec(row.url || '') : null
  const coverUrl = row.cover_url || (bvMatch ? `/api/bili-cover?bvid=${bvMatch[1]}` : '')
  const hasCover = Boolean(coverUrl) && (
    isYoutubeRow || isBiliRow ||
    /ytimg\.com\//i.test(coverUrl) ||
    /hdslb\.com\//i.test(coverUrl)
  )

  // 动画优化：检测是否应减少动画
  const shouldReduceMotion = useReducedMotion()

  // suppress unused groupId lint warning — used externally as key
  void groupId

  return (
    <motion.div
      initial={shouldReduceMotion ? undefined : { opacity: 0, y: 10 }}
      animate={shouldReduceMotion ? undefined : { opacity: 1, y: 0 }}
      transition={shouldReduceMotion ? { duration: 0 } : { delay: Math.min(idx * 0.02, 0.15) }}
      className="timeline-item"
    >
      <article
        className={`glass timeline-content timeline-compact${isHigh ? ' timeline-high' : ''}${isHovered ? ' hover-open' : ''}`}
        onMouseEnter={() => onHoverEnter(rowKey)}
        onMouseLeave={() => onHoverLeave(rowKey)}
      >
        <div className="t-header" style={{ marginBottom: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
            <span className="source-badge" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <SourceLogo row={row} />
              {row.source}
            </span>
            {row.enriched && (
              <span
                title="已完成全文深化分析"
                style={{
                  fontSize: 10,
                  fontWeight: 800,
                  letterSpacing: 0.5,
                  textTransform: 'uppercase',
                  color: '#34d399',
                  border: '1px solid rgba(52, 211, 153, 0.4)',
                  background: 'rgba(52, 211, 153, 0.08)',
                  padding: '2px 6px',
                  borderRadius: 999,
                  lineHeight: 1.2,
                  flexShrink: 0,
                }}
              >
                Enriched
              </span>
            )}
            <span suppressHydrationWarning className="node-time" title={`${row.time} ${formatShortTime(row.time)}`}>
              {formatRelativeTime(row.time, now)}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <ScoreBar score={s} />
            <div className={`node-dot ${isHigh ? 'glow-green' : isMid ? 'glow-blue' : 'glow-gray'}`} />
            <a href={row.url} target="_blank" rel="noreferrer" aria-label="打开原文" style={{ display: 'inline-flex', alignItems: 'center' }}>
              <ExternalLink size={13} color="#8aa3be" />
            </a>
          </div>
        </div>

        <a href={row.url} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
          <h3 className="t-title">{row.title || row.hidden_signal || '未命名信号'}</h3>
        </a>

        {hasCover && (
          <a href={row.url} target="_blank" rel="noreferrer" className="t-cover-wrap" aria-label="打开原文封面">
            <img className="t-cover" src={coverUrl} alt={row.title || '封面图'} loading="lazy" width={480} height={270} />
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

        {!hasAiContent && (row.hidden_signal || row.core_event || row.actionable) && (
          <p className="t-reason-preview t-reason-single" style={{ margin: 0 }}>
            {row.hidden_signal || row.core_event || row.actionable}
          </p>
        )}

        {hasAiContent && <p className="t-expand-hint">悬停查看 AI 分析</p>}

        <div className={`t-ai-content${isHovered ? ' expanded' : ''}`}>
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
        </div>
      </article>
    </motion.div>
  )
})

export default FeedCard
