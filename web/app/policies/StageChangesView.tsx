'use client'
import { useState } from 'react'
import Link from 'next/link'
import {
  GitCompareArrows,
  TrendingUp,
  TrendingDown,
  ExternalLink,
  Sparkles,
  Hash,
} from 'lucide-react'
import type { PolicyChange } from '../../lib/journal-store'
import { dateLabel } from '../../lib/journal-utils'

/**
 * 阶段变化双栏视图（政策库 mode=changes 的列表主体）。
 * 左列 = 变化流（选中态）；右列 = 选中变化的完整纪要面板：
 *   变化概要 / 数字变化表 / 措辞强度 / 新增·消失议题 / 新提法 / 两期原文入口。
 * 列表行设计为"一条变化一行信号"：显著性 + 阶段定性 + 一句话摘要。
 */
export default function StageChangesView({ changes }: { changes: PolicyChange[] }) {
  const [active, setActive] = useState(0)
  const cur = changes[active]
  if (!cur) return null
  return (
    <div className="stage-view">
      <ol className="stage-view-list" aria-label="阶段变化列表">
        {changes.map((c, i) => (
          <li key={i}>
            <button
              aria-pressed={i === active}
              onClick={() => setActive(i)}
              className="stage-view-row"
            >
              <span className={`pill ${sig(c.verdict.significance)}`}>
                {c.verdict.significance || '低'}
              </span>
              <span className="stage-view-body">
                <b>{c.verdict.stage_verdict || seriesName(c.series_key)}</b>
                <small>{c.verdict.summary?.slice(0, 56)}</small>
              </span>
              <time>{dateLabel(c.created_at, true)}</time>
            </button>
          </li>
        ))}
      </ol>
      <aside className="stage-view-detail" aria-label="变化详情">
        <header>
          <GitCompareArrows size={16} />
          <b>{cur.verdict.stage_verdict || '跨期对比'}</b>
          <span className={`pill ${sig(cur.verdict.significance)}`}>
            {cur.verdict.significance || '低'}显著
          </span>
          <time>{dateLabel(cur.created_at, true)}</time>
        </header>
        <p className="stage-view-series">
          {cur.prev_title} <span aria-hidden>→</span> {cur.curr_title}
        </p>
        {cur.verdict.summary && <p className="stage-view-summary">{cur.verdict.summary}</p>}

        {!!cur.verdict.numeric_changes?.length && (
          <section>
            <h3><Hash size={12} /> 数字变化</h3>
            <table className="stage-num-table">
              <tbody>
                {cur.verdict.numeric_changes.map((n, i) => (
                  <tr key={i}>
                    <th>{n.metric}</th>
                    <td className="old">{n.old_value}</td>
                    <td className="new">{n.new_value}</td>
                    <td className="why">{n.meaning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        {!!cur.verdict.intensity_changes?.length && (
          <section>
            <h3><Sparkles size={12} /> 措辞强度</h3>
            <ul>
              {cur.verdict.intensity_changes.map((n, i) => (
                <li key={i}>
                  {n.direction === '强化' ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
                  <div>
                    <b>{n.topic}</b>
                    <p>
                      <q>{n.old_wording}</q> → <q>{n.new_wording}</q>
                      <em>{n.direction}</em>
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {(!cur.verdict.new_issues?.length && !cur.verdict.dropped_issues?.length) || (
          <section className="stage-view-issues">
            {!!cur.verdict.new_issues?.length && (
              <div>
                <h4>新增议题</h4>
                <ul>{cur.verdict.new_issues.map((x, i) => <li key={i}>{x}</li>)}</ul>
              </div>
            )}
            {!!cur.verdict.dropped_issues?.length && (
              <div>
                <h4>淡出议题</h4>
                <ul>{cur.verdict.dropped_issues.map((x, i) => <li key={i}>{x}</li>)}</ul>
              </div>
            )}
          </section>
        )}

        {!!cur.verdict.new_formulations?.length && (
          <section>
            <h3><Sparkles size={12} /> 新提法</h3>
            <p className="stage-tags">
              {cur.verdict.new_formulations.map((x, i) => (
                <span key={i} className="pill clay">{x}</span>
              ))}
            </p>
          </section>
        )}

        {cur.verdict.priority_shift && (
          <section>
            <h3>优先级位移</h3>
            <p>{cur.verdict.priority_shift}</p>
          </section>
        )}

        <footer className="stage-view-docs">
          <Link href={`/policies/${encodeURIComponent(cur.prev_id)}`} className="text-link">
            上期原文 <ExternalLink size={11} />
          </Link>
          <Link href={`/policies/${encodeURIComponent(cur.curr_id)}`} className="text-link">
            本期原文 <ExternalLink size={11} />
          </Link>
        </footer>
      </aside>
    </div>
  )
}

function sig(s?: string) {
  if (s === '高') return 'clay'
  if (s === '中') return ''
  return 'neutral'
}

function seriesName(key: string) {
  const m = key.match(/《(.+?)》/)
  return m ? m[1] : key.replace(/^generic:/, '').slice(0, 20)
}
