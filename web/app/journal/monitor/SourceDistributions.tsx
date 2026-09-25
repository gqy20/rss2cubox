import { Rss, Files } from 'lucide-react'
import type { MonitorStatus } from '../../../lib/monitor-types'
import { monitorLabels } from '../../../lib/monitor-utils'

export type Distribution = {
  type: 'tech' | 'policy'
  total: number
  counts: { key: MonitorStatus; count: number }[]
}
export default function SourceDistributions({
  distributions,
  update,
}: {
  distributions: Distribution[]
  update: (changes: Record<string, string | null>) => void
}) {
  return (
    <section className="source-distributions" aria-label="信源最近一轮状态分布">
      {distributions.map(({ type, total, counts }) => (
        <div className="source-distribution" key={type}>
          <button
            className="distribution-name"
            onClick={() =>
              update({ kind: type, status: null, error: null, view: 'all' })
            }
          >
            {type === 'tech' ? <Rss size={15} /> : <Files size={15} />}
            <span>{type === 'tech' ? '科技源' : '政策源'}</span>
            <b>{total}</b>
          </button>
          <div className="distribution-bar">
            {counts.map(({ key, count }) => (
              <button
                key={key}
                style={{ flex: count }}
                className={`distribution-segment ${key}`}
                aria-label={`${type === 'tech' ? '科技' : '政策'}${monitorLabels[key]} ${count}个信源`}
                title={`${monitorLabels[key]} ${count}`}
                onClick={() =>
                  update({
                    kind: type,
                    status: key,
                    error: null,
                    view: 'all',
                  })
                }
              />
            ))}
          </div>
          <div className="distribution-legend">
            {counts.map(({ key, count }) => (
              <button
                key={key}
                onClick={() =>
                  update({
                    kind: type,
                    status: key,
                    error: null,
                    view: 'all',
                  })
                }
              >
                <i className={`legend-dot ${key}`} />
                {monitorLabels[key]}
                <b>{count}</b>
              </button>
            ))}
          </div>
        </div>
      ))}
    </section>
  )
}
