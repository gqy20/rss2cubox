import type { Policy } from '../../lib/journal-types'
export default function PolicyApplicability({
  policy,
  evidenceHref,
}: {
  policy: Policy
  evidenceHref?: string
}) {
  const dates = [
    policy.effective_date ? `生效 ${policy.effective_date}` : null,
    policy.comment_deadline ? `征集截止 ${policy.comment_deadline}` : null,
  ].filter(Boolean)
  return (
    <section className="policy-applicability" aria-label="适用性速览">
      <div className="policy-applicability-heading">
        <h3>适用性速览</h3>
        <span className="ai-label">
          {policy.enriched_at ? '结构化提取' : '待分析'}
        </span>
        <span className="policy-stage">
          {policy.stage && policy.stage !== '不明'
            ? policy.stage
            : '阶段未明确'}
        </span>
        {evidenceHref && (
          <a className="text-link" href={evidenceHref}>
            核对依据
          </a>
        )}
      </div>
      <dl>
        <div>
          <dt>涉及谁</dt>
          <dd>
            {policy.affected_parties?.length
              ? policy.affected_parties.join('、')
              : '原文未明确适用主体'}
          </dd>
        </div>
        <div>
          <dt>要求性质</dt>
          <dd>
            {[policy.instrument_type, policy.obligation_level]
              .filter(Boolean)
              .join(' · ') || '原文未明确'}
          </dd>
        </div>
        <div>
          <dt>关键时间</dt>
          <dd>{dates.length ? dates.join(' · ') : '原文未明确日期'}</dd>
        </div>
      </dl>
    </section>
  )
}
