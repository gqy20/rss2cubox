import { Clock3 } from 'lucide-react'
import type { MonitorSource, SourceRun } from '../../../lib/monitor-types'
import {
  monitorLabels,
  errorCategory,
  isStale,
} from '../../../lib/monitor-utils'
import { dateLabel } from '../../../lib/journal-utils'

export function elapsed(value: string | null, now: number) {
  if (!value) return '从未记录'
  const hours = Math.max(0, (now - Date.parse(value)) / 3600000)
  return hours < 1
    ? `${Math.floor(hours * 60)}分钟前`
    : hours < 24
      ? `${Math.floor(hours)}小时前`
      : `${Math.floor(hours / 24)}天前`
}
export function historyLabel(run: SourceRun) {
  return `${dateLabel(run.at, true)} · ${monitorLabels[run.status]} · ${run.fetched}条 · ${run.attempts}次请求`
}
export function Heartbeat({ source }: { source: MonitorSource }) {
  const runs = [
    ...Array(Math.max(0, 12 - source.runs.length)).fill(null),
    ...source.runs.slice(0, 12).reverse(),
  ] as (SourceRun | null)[]
  return (
    <span
      className="heartbeat"
      role="img"
      aria-label={`最近${source.runs.length}轮：${
        source.runs
          .slice()
          .reverse()
          .map((r) => monitorLabels[r.status])
          .join('、') || '暂无记录'
      }`}
    >
      {runs.map((run, i) => (
        <i
          key={run?.id || i}
          className={`heartbeat-cell ${run?.status || 'missing'}`}
          aria-hidden="true"
          title={run ? historyLabel(run) : '无历史记录'}
        >
          {run?.status === 'failed'
            ? '!'
            : run?.status === 'empty'
              ? '−'
              : run?.status === 'skipped'
                ? '·'
                : ''}
        </i>
      ))}
    </span>
  )
}
export function Status({
  source,
  now,
  hours,
}: {
  source: MonitorSource
  now: number
  hours: number
}) {
  return (
    <div className="source-condition">
      <span className={`source-status ${source.status}`}>
        {source.status === 'failed'
          ? errorCategory(source.runs[0]?.error)
          : monitorLabels[source.status]}
      </span>
      {source.failureStreak > 1 && source.status === 'failed' && (
        <small>
          连续{source.failureStreak === 12 ? '≥12' : source.failureStreak}轮失败
        </small>
      )}
      {source.emptyStreak >= 3 && (
        <small>
          连续
          {source.emptyStreak >= 12 && source.kind === 'tech'
            ? '≥12'
            : source.emptyStreak}
          轮空结果
        </small>
      )}
      {source.recovered && source.status === 'ok' && (
        <small className="recovered-note">最近一轮已恢复</small>
      )}
      {isStale(source, now, hours) && (
        <small className="stale-note">
          <Clock3 size={11} />超{hours}h未采集
        </small>
      )}
    </div>
  )
}
