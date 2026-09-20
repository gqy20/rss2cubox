import Link from 'next/link'
import type { LineageStats } from '../../lib/journal-store'

// 政策主线趋势条：未选主线时是五条线的计数横条（点选进入单线视图），
// 选中主线后切换为该线的月份分布 + 立法阶段漏斗。纯服务端渲染，切换走 URL。
export default function LineageStrip({
  stats,
  selected,
}: {
  stats: LineageStats
  selected: string
}) {
  if (!stats.lineages.length) return null
  if (!selected) {
    const max = Math.max(...stats.lineages.map((l) => l.n))
    return (
      <nav className="lineage-strip" aria-label="政策主线分布">
        {stats.lineages.map(({ lineage, n }) => (
          <Link
            key={lineage}
            href={`/policies?policy_lineage=${encodeURIComponent(lineage)}`}
            className="lineage-row"
          >
            <span className="lineage-name">{lineage}</span>
            <span className="lineage-bar">
              <span style={{ width: `${Math.round((n / max) * 100)}%` }} />
            </span>
            <span className="lineage-count">{n}</span>
          </Link>
        ))}
      </nav>
    )
  }
  const maxMonth = Math.max(1, ...stats.months.map((m) => m.n))
  return (
    <div className="lineage-strip selected">
      <div className="lineage-head">
        <strong>{selected}</strong>
        <Link href="/policies">全部主线</Link>
      </div>
      {stats.months.length > 0 && (
        <div className="lineage-months" aria-label="按月发布分布">
          {stats.months.map(({ ym, n }) => (
            <div key={ym} className="lineage-month" title={`${ym}：${n} 份`}>
              <span
                className="lineage-month-bar"
                style={{ height: `${Math.max(8, Math.round((n / maxMonth) * 100))}%` }}
              />
              <span className="lineage-month-n">{n}</span>
              <span className="lineage-month-label">{ym.slice(2)}</span>
            </div>
          ))}
        </div>
      )}
      {stats.stages.length > 0 && (
        <div className="lineage-stages" aria-label="立法阶段分布">
          {stats.stages.map(({ stage, n }) => (
            <span key={stage} className={`pill ${stagePill(stage)}`}>
              {stage} {n}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function stagePill(stage: string) {
  if (stage === '征求意见') return 'clay'
  if (stage === '已生效') return 'olive'
  return ''
}
