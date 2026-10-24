import Link from 'next/link'
import { GitCompareArrows, TrendingUp, TrendingDown } from 'lucide-react'
import type { PolicyChange } from '../../lib/journal-store'
import { dateLabel } from '../../lib/journal-utils'

/**
 * 阶段变化区块：政策系列相邻两期的跨期比较纪要（LLM 产出）。
 * 展示维度为"变化"而非"文件"——数字目标变化与措辞强度变化是核心信号。
 */
export default function StageShifts({ changes }: { changes: PolicyChange[] }) {
  if (!changes.length) return null
  const top = changes[0]
  return (
    <details className="surface stage-shifts">
      <summary aria-label="展开政策阶段变化">
        <GitCompareArrows size={17} />
        <b>阶段变化</b>
        {top.verdict?.significance && (
          <span className={`pill ${sigClass(top.verdict.significance)}`}>
            {top.verdict.significance}显著
          </span>
        )}
        <span className="stage-shifts-teaser">{top.verdict?.summary?.slice(0, 44) || '同系列文件跨期对比'}</span>
        <span className="stage-shifts-sub">AI 生成 · {changes.length} 期对比</span>
      </summary>
      {changes.map((c, i) => (
        <article key={i} className="stage-shift">
          <header>
            <span className={`pill ${sigClass(c.verdict.significance)}`}>
              {c.verdict.significance || '低'}显著
            </span>
            {c.verdict.stage_verdict && (
              <span className="stage-verdict">{c.verdict.stage_verdict}</span>
            )}
            <time>{dateLabel(c.created_at, true)}</time>
          </header>
          <p className="stage-series">
            {shortTitle(c.prev_title)} → {shortTitle(c.curr_title)}
          </p>
          {c.verdict.summary && (
            <p className="stage-summary">{c.verdict.summary}</p>
          )}
          {!!c.verdict.numeric_changes?.length && (
            <ul className="stage-numerics">
              {c.verdict.numeric_changes.slice(0, 4).map((n, j) => (
                <li key={j}>
                  <b>{n.metric}</b>
                  <span className="old">{n.old_value}</span>→
                  <span className="new">{n.new_value}</span>
                  {n.meaning && <small>{n.meaning}</small>}
                </li>
              ))}
            </ul>
          )}
          {!!c.verdict.intensity_changes?.length && (
            <ul className="stage-intensity">
              {c.verdict.intensity_changes.slice(0, 3).map((n, j) => (
                <li key={j}>
                  {n.direction === '强化' ? (
                    <TrendingUp size={12} />
                  ) : (
                    <TrendingDown size={12} />
                  )}
                  <b>{n.topic}</b>
                  <q>{n.old_wording}</q>→<q>{n.new_wording}</q>
                </li>
              ))}
            </ul>
          )}
          <div className="stage-links">
            <Link href={`/policies/${encodeURIComponent(c.prev_id)}`} className="text-link">
              上期原文
            </Link>
            <Link href={`/policies/${encodeURIComponent(c.curr_id)}`} className="text-link">
              本期原文
            </Link>
          </div>
        </article>
      ))}
    </details>
  )
}

function shortTitle(t: string) {
  const m = t.match(/《(.+?)》/)
  return (m ? m[1] : t).slice(0, 22)
}

function sigClass(sig?: string) {
  if (sig === '高') return 'clay'
  if (sig === '中') return ''
  return 'neutral'
}
