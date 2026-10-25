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
import type { DiffSegment, PolicyChange } from '../../lib/journal-store'
import { dateLabel } from '../../lib/journal-utils'

/**
 * 阶段变化详情（Reader 右栏，id=change:<n>）。
 * 两个 tab 由 Reader 的 document-tabs 切换（?tab=）：summary=变化纪要，original=原文对照。
 */
export default function StageChangeDetail({
  change,
  tab,
}: {
  change: PolicyChange
  tab: 'summary' | 'original'
}) {
  return tab === 'original' ? (
    <DiffBlocks segments={change.diff_segments || []} />
  ) : (
    <VerdictSections change={change} />
  )
}

/** 变化纪要：速览卡 → AI 纪要 → 数字/措辞/议题/新提法/优先级 → 两期原文入口 */
function VerdictSections({ change }: { change: PolicyChange }) {
  const v = change.verdict
  return (
    <>
      <section className="stage-glance" aria-label="变化速览">
        <div className="stage-glance-heading">
          <h3>变化速览</h3>
          <span className="ai-label">AI 跨期对比</span>
          <span className={`pill ${significanceClass(v.significance)}`}>
            {v.significance || '低'}显著
          </span>
        </div>
        <dl className="stage-glance-facts">
          <div>
            <dt>阶段判断</dt>
            <dd>{v.stage_verdict || '—'}</dd>
          </div>
          <div>
            <dt>比较期</dt>
            <dd>{dateLabel(change.created_at, true)}</dd>
          </div>
          <div className="stage-glance-wide">
            <dt>对比对象</dt>
            <dd>
              {shortTitle(change.prev_title)} <span aria-hidden>→</span>{' '}
              {shortTitle(change.curr_title)}
            </dd>
          </div>
        </dl>
      </section>

      {v.summary && (
        <div className="document-section">
          <h3>
            变化纪要 <span className="ai-label">AI 提炼</span>
          </h3>
          <p>{v.summary}</p>
        </div>
      )}

      {!!v.numeric_changes?.length && (
        <div className="document-section">
          <h3>
            <Hash size={14} /> 数字变化
          </h3>
          <table className="stage-num-table">
            <tbody>
              {v.numeric_changes.map((n, i) => (
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

      {!!v.intensity_changes?.length && (
        <div className="document-section">
          <h3>
            <Sparkles size={14} /> 措辞强度
          </h3>
          <ul className="stage-intensity-list">
            {v.intensity_changes.map((n, i) => (
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

      {(!!v.new_issues?.length || !!v.dropped_issues?.length) && (
        <div className="document-section stage-view-issues">
          {!!v.new_issues?.length && (
            <div>
              <h3>新增议题</h3>
              <ul>{v.new_issues.map((x, i) => <li key={i}>{x}</li>)}</ul>
            </div>
          )}
          {!!v.dropped_issues?.length && (
            <div>
              <h3>淡出议题</h3>
              <ul>{v.dropped_issues.map((x, i) => <li key={i}>{x}</li>)}</ul>
            </div>
          )}
        </div>
      )}

      {!!v.new_formulations?.length && (
        <div className="document-section">
          <h3>新提法</h3>
          <p className="stage-tags">
            {v.new_formulations.map((x, i) => (
              <span key={i} className="pill clay">{x}</span>
            ))}
          </p>
        </div>
      )}

      {v.priority_shift && (
        <div className="document-section">
          <h3>
            <GitCompareArrows size={14} /> 优先级位移
          </h3>
          <p>{v.priority_shift}</p>
        </div>
      )}

      <div className="document-section stage-view-docs">
        <Link
          className="primary-button"
          href={`/policies/${encodeURIComponent(change.prev_id)}`}
        >
          阅读上期原文 <ArrowRight size={15} />
        </Link>
        <Link
          className="primary-button"
          href={`/policies/${encodeURIComponent(change.curr_id)}`}
        >
          阅读本期原文 <ArrowRight size={15} />
        </Link>
      </div>
    </>
  )
}

/** 原文对照：difflib 段落 diff（agent 预计算）。连续未变段折叠成一行，改动段左右并排。 */
function DiffBlocks({ segments }: { segments: DiffSegment[] }) {
  const [open, setOpen] = useState<Set<number>>(new Set())
  if (!segments.length)
    return (
      <div className="document-section">
        <h3>原文对照</h3>
        <p className="text-muted">原文对照尚未生成，对比 agent 下轮运行时自动补齐。</p>
      </div>
    )
  // 连续 same 段合并为一个折叠组，其余逐段渲染
  const groups: (
    | { kind: 'same'; key: number; items: string[] }
    | { kind: 'diff'; key: number; item: DiffSegment }
  )[] = []
  for (const s of segments) {
    const last = groups.at(-1)
    if (s.type === 'same' && last?.kind === 'same') last.items.push(s.text)
    else if (s.type === 'same') groups.push({ kind: 'same', key: groups.length, items: [s.text] })
    else groups.push({ kind: 'diff', key: groups.length, item: s })
  }
  const toggle = (key: number) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  return (
    <div className="diff-blocks" aria-label="原文对照">
      <div className="diff-legend">
        <span>上期</span>
        <span>本期</span>
      </div>
      {groups.map((g) =>
        g.kind === 'same' ? (
          <div key={g.key} className="diff-same-group">
            <button
              className="diff-same-toggle"
              aria-expanded={open.has(g.key)}
              onClick={() => toggle(g.key)}
            >
              {open.has(g.key) ? '收起' : '展开'}未变段落 {g.items.length} 段
            </button>
            {open.has(g.key) &&
              g.items.map((text, i) => (
                <p key={i} className="diff-same-text">{text}</p>
              ))}
          </div>
        ) : (
          <div key={g.key} className={`diff-row diff-${g.item.type}`}>
            <p className="diff-prev">
              {g.item.type === 'changed' && g.item.prev ? (
                <Marked text={g.item.prev} marks={g.item.prev_marks} />
              ) : (
                ('prev' in g.item && g.item.prev) || <span aria-hidden>—</span>
              )}
            </p>
            <p className="diff-curr">
              {g.item.type === 'changed' && g.item.curr ? (
                <Marked text={g.item.curr} marks={g.item.curr_marks} />
              ) : (
                ('curr' in g.item && g.item.curr) || <span aria-hidden>—</span>
              )}
            </p>
          </div>
        ),
      )}
    </div>
  )
}

/** 按 agent 预计算的区间把差异字圈成 <mark>；无 marks 时整段原样。 */
function Marked({ text, marks }: { text: string; marks?: number[][] }) {
  if (!marks?.length) return <>{text}</>
  const parts: React.ReactNode[] = []
  let pos = 0
  for (const [start, end] of marks) {
    if (start > pos) parts.push(text.slice(pos, start))
    parts.push(<mark key={start}>{text.slice(start, end)}</mark>)
    pos = end
  }
  if (pos < text.length) parts.push(text.slice(pos))
  return <>{parts}</>
}

function significanceClass(s?: string) {
  if (s === '高') return 'clay'
  if (s === '中') return ''
  return 'neutral'
}

function shortTitle(t: string) {
  const m = t.match(/《(.+?)》/)
  return (m ? m[1] : t).slice(0, 26)
}
