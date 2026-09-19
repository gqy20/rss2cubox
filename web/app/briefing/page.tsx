import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'
import { readInsightHistory } from '../../lib/journal-store'
import { dateLabel, insightItems, excerpt } from '../../lib/journal-utils'
import { PageHeading, ExternalLink, Empty } from '../journal/Shared'
import { ExportButton } from '../journal/Actions'
export const dynamic = 'force-dynamic'
export default async function BriefingPage({
  searchParams,
}: {
  searchParams: Promise<{ at?: string }>
}) {
  const { at } = await searchParams,
    history = await readInsightHistory()
  const selected = history.find((h) => h.generated_at === at) || history[0]
  return (
    <>
      <Link className="breadcrumb" href="/">
        <ArrowLeft size={14} />
        返回今日简报
      </Link>
      <PageHeading title="洞察与行动">
        {selected && <ExportButton data={selected} name="insights" />}
      </PageHeading>
      {history.length > 0 && (
        <form className="toolbar" action="/briefing" method="get">
          <label>
            历史简报
            <select name="at" defaultValue={selected.generated_at}>
              {history.map((h) => (
                <option key={h.generated_at} value={h.generated_at}>
                  {dateLabel(h.generated_at, true)}
                </option>
              ))}
            </select>
          </label>
          <button className="soft-button" type="submit">
            查看这一期
          </button>
          <span className="snapshot-note" style={{ margin: 0 }}>
            最近30期 · 全部内容由 AI 提炼
          </span>
        </form>
      )}
      {selected ? (
        (['trends', 'weak_signals', 'daily_advices'] as const).map((key, i) => (
          <section className="surface" key={key} style={{ marginBottom: 22 }}>
            <h2 style={{ fontFamily: 'var(--serif)', marginBottom: 20 }}>
              {['宏观技术趋势', '暗流弱信号', '行动建议'][i]}
            </h2>
            {insightItems(selected.data[key]).map((item, index) => (
              <details className="disclosure" key={index} open={index === 0}>
                <summary>{excerpt(item.text, 100)}</summary>
                <div className="prose">
                  <p>{item.text}</p>
                  <div className="source-links">
                    {item.source_urls?.map((url, j) => (
                      <ExternalLink key={url} url={url}>
                        {item.source_titles?.[j] || `来源${j + 1}`}
                      </ExternalLink>
                    ))}
                  </div>
                </div>
              </details>
            ))}
            {insightItems(selected.data[key]).length === 0 && (
              <Empty title="这一期暂无此类洞察" />
            )}
          </section>
        ))
      ) : (
        <section className="surface">
          <Empty
            title="等待第一期洞察"
            description="全局分析完成后，趋势、弱信号和建议会出现在这里。"
          />
        </section>
      )}
    </>
  )
}
