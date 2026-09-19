import type { ReactNode } from 'react'

/** Ordinal model ratings are not probabilities. Keep the exact score accessible. */
export function ScoreIndicator({
  label,
  value,
}: {
  label: string
  value?: number | null
}) {
  if (value == null || !Number.isFinite(value) || value < 1 || value > 5) {
    return (
      <span className="score-indicator">
        <span>{label}</span>
        <span className="muted-text">未记录</span>
      </span>
    )
  }
  const score = Math.round(value)
  return (
    <span
      className="score-indicator"
      role="img"
      aria-label={`${label} ${value}/5`}
      title={`${label} ${value}/5`}
    >
      <span aria-hidden="true">{label}</span>
      <span className="score-ticks" aria-hidden="true">
        {[1, 2, 3, 4, 5].map((n) => (
          <i key={n} className={n <= score ? 'filled' : ''} />
        ))}
      </span>
    </span>
  )
}
export function CountLabel({
  icon,
  label,
  value,
}: {
  icon: ReactNode
  label: string
  value: number | string
}) {
  return (
    <span className="count-label" title={label}>
      <span aria-hidden="true">{icon}</span>
      <span>{label}</span>
      <b>{typeof value === 'number' ? value.toLocaleString() : value}</b>
    </span>
  )
}
export function Coverage({
  label,
  value,
  total,
  compact = false,
}: {
  label: string
  value?: number | null
  total?: number | null
  compact?: boolean
}) {
  const available = value != null && total != null
  return (
    <div className={`coverage-line ${compact ? 'coverage-compact' : ''}`}>
      <div className="coverage-caption">
        <span>{label}</span>
        <b>
          {available ? value.toLocaleString() : '—'}
          <span className="ratio-total">
            {' '}
            / {available ? total.toLocaleString() : '—'}
          </span>
        </b>
      </div>
      {available && total > 0 ? (
        <progress
          max={total}
          value={value}
          aria-label={`${label} ${value}/${total}`}
        />
      ) : (
        <span className="coverage-unavailable">
          {available ? '暂无数据' : '暂不可用'}
        </span>
      )}
    </div>
  )
}
