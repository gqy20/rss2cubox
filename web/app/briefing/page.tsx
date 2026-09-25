import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'
import { readInsightHistory } from '../../lib/journal-store'
import { dateLabel, insightItems, excerpt } from '../../lib/journal-utils'
import { PageHeading, ExternalLink, Empty } from '../journal/Shared'
import { ExportButton } from '../journal/Actions'
import { SearchTrigger } from '../journal/SearchPalette'
export const dynamic = 'force-dynamic'
export default async function BriefingPage({
  searchParams,
}: {
  searchParams: Promise<{ at?: string }>
}) {
  const { at } = await searchParams,
    history = await readInsightHistory()
  const selected = history.find((h) => h.generated_at === at) || history[0],
    // The requested issue is outside the 30-issue window — say so instead of
    // silently showing the latest one.
    missed = Boolean(at && history.length && !history.find((h) => h.generated_at === at))
  return (
    <>
      <div className="briefing-topline">
        <Link className="breadcrumb" href="/">
          <ArrowLeft size={14} />
          返回今日简报
        </Link>
        <div className="heading-actions">
          <SearchTrigger />
          {selected && <ExportButton data={selected} name="insights" />}
        </div>
      </div>
      <PageHeading title="洞察与行动" />
      {missed && (
        <div className="data-notice" role="status">
          要找的那期不在最近30期内，已展示最新一期。
        </div>
      )}
      {history.length > 0 && (
        <form className="toolbar" action="/briefing" method="get">
          <label>
            <span className="sr-only">历史简报</span>
            <select name="at" aria-label="历史简报" defaultValue={selected.generated_at}>
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
          <span className="snapshot-note briefing-form-note">
            最近30期 · 全部内容由 AI 提炼
          </span>
        </form>
      )}
      {selected ? (
        (['trends', 'weak_signals', 'daily_advices'] as const).map((key, i) => {
          const items = insightItems(selected.data[key])
          return (
          <section className="surface briefing-section" key={key}>
            <h2>
              {['宏观技术趋势', '暗流弱信号', '行动建议'][i]}
            </h2>
            {items.map((item, index) => (
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
            {items.length === 0 && (
              <Empty title="这一期暂无此类洞察" />
            )}
          </section>
          )
        })
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
