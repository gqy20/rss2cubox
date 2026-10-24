'use client'
import { useState } from 'react'
import Link from 'next/link'
import {
  GitCompareArrows,
  TrendingUp,
  TrendingDown,
  Sparkles,
  Hash,
  ArrowRight,
} from 'lucide-react'
import type { PolicyChange } from '../../lib/journal-store'
import { dateLabel } from '../../lib/journal-utils'

/**
 * 阶段变化双栏视图（政策库 mode=changes 的列表主体）。
 * 右栏层级与其他视图的阅读详情对齐：
 *   变化速览卡（显著性+阶段定性+系列+日期）
 *   → document-section（16px 节标题 + 衬线正文）
 *   → 证据引句框（措辞强度的新旧原文）
 *   → 底部主操作（两期原文，primary-button 同款）
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
        <section className="stage-glance" aria-label="变化速览">
          <div className="stage-glance-heading">
            <h3>变化速览</h3>
            <span className="ai-label">AI 跨期对比</span>
            <span className={`pill ${sig(cur.verdict.significance)}`}>
              {cur.verdict.significance || '低'}显著
            </span>
          </div>
          <dl className="stage-glance-facts">
            <div>
              <dt>阶段判断</dt>
              <dd>{cur.verdict.stage_verdict || '—'}</dd>
            </div>
            <div>
              <dt>比较期</dt>
              <dd>{dateLabel(cur.created_at, true)}</dd>
            </div>
            <div className="stage-glance-wide">
              <dt>对比对象</dt>
              <dd>
                {shortTitle(cur.prev_title)} <span aria-hidden>→</span>{' '}
                {shortTitle(cur.curr_title)}
              </dd>
            </div>
          </dl>
        </section>

        {cur.verdict.summary && (
          <div className="document-section">
            <h3>
              变化纪要 <span className="ai-label">AI 提炼</span>
            </h3>
            <p>{cur.verdict.summary}</p>
          </div>
        )}

        {!!cur.verdict.numeric_changes?.length && (
          <div className="document-section">
            <h3>
              <Hash size={14} /> 数字变化
            </h3>
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
          </div>
        )}

        {!!cur.verdict.intensity_changes?.length && (
          <div className="document-section">
            <h3>
              <Sparkles size={14} /> 措辞强度
            </h3>
            <ul className="stage-intensity-list">
              {cur.verdict.intensity_changes.map((n, i) => (
                <li key={i}>
                  <span className="stage-intensity-head">
                    {n.direction === '强化' ? (
                      <TrendingUp size={13} />
                    ) : (
                      <TrendingDown size={13} />
                    )}
                    <b>{n.topic}</b>
                    <em>{n.direction}</em>
                  </span>
                  <div className="quote-box stage-quote">
                    <small>新旧原文对照 · 请与原文核对</small>
                    <p>
                      <q>{n.old_wording}</q>
                      <span aria-hidden> → </span>
                      <q>{n.new_wording}</q>
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {(!cur.verdict.new_issues?.length && !cur.verdict.dropped_issues?.length) || (
          <div className="document-section stage-view-issues">
            {!!cur.verdict.new_issues?.length && (
              <div>
                <h3>新增议题</h3>
                <ul>{cur.verdict.new_issues.map((x, i) => <li key={i}>{x}</li>)}</ul>
              </div>
            )}
            {!!cur.verdict.dropped_issues?.length && (
              <div>
                <h3>淡出议题</h3>
                <ul>{cur.verdict.dropped_issues.map((x, i) => <li key={i}>{x}</li>)}</ul>
              </div>
            )}
          </div>
        )}

        {!!cur.verdict.new_formulations?.length && (
          <div className="document-section">
            <h3>新提法</h3>
            <p className="stage-tags">
              {cur.verdict.new_formulations.map((x, i) => (
                <span key={i} className="pill clay">{x}</span>
              ))}
            </p>
          </div>
        )}

        {cur.verdict.priority_shift && (
          <div className="document-section">
            <h3>
              <GitCompareArrows size={14} /> 优先级位移
            </h3>
            <p>{cur.verdict.priority_shift}</p>
          </div>
        )}

        <div className="document-section stage-view-docs">
          <Link
            className="primary-button"
            href={`/policies/${encodeURIComponent(cur.prev_id)}`}
          >
            阅读上期原文 <ArrowRight size={15} />
          </Link>
          <Link
            className="primary-button"
            href={`/policies/${encodeURIComponent(cur.curr_id)}`}
          >
            阅读本期原文 <ArrowRight size={15} />
          </Link>
        </div>
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

function shortTitle(t: string) {
  const m = t.match(/《(.+?)》/)
  return (m ? m[1] : t).slice(0, 26)
}
