import dynamic from 'next/dynamic'
import type { ArticleStats, PolicyStats } from '../../../lib/journal-types'
import { dateLabel } from '../../../lib/journal-utils'
import { Empty, PanelHeading } from '../Shared'
import { Coverage } from '../Numbers'
const TrendChart = dynamic(() => import('../TrendChart'), {
  ssr: false,
  loading: () => <div className="loading-skeleton" />,
})
export default function StatsView({
  trend,
  stats,
  policyStats,
  loadedAt,
}: {
  trend: { day: string; articles: number; policies: number }[] | null
  stats: ArticleStats | null
  policyStats: PolicyStats | null
  loadedAt: string
}) {
  return (
    <div className="monitor-statistics">
      <div className="monitor-grid">
        <section className="surface">
          <PanelHeading title="近两周入库变化" />
          {trend ? (
            <TrendChart data={trend} />
          ) : (
            <Empty title="暂无入库趋势" />
          )}
        </section>
        <section className="surface">
          <PanelHeading title="分析覆盖" />
          <Coverage
            label="文章已分析"
            value={stats?.analyzed}
            total={stats?.total}
          />
          <Coverage
            label="政策已分析"
            value={policyStats?.analyzed}
            total={policyStats?.total}
          />
          <p className="snapshot-note">
            未分析数量不等于待处理队列。政策预筛会跳过低相关内容。
          </p>
        </section>
      </div>
      <section className="surface">
        <h2>统计口径</h2>
        <ul className="evidence-list">
          <li>
            同一信源、同一运行编号的请求合并为一轮。备用地址成功则整轮成功；条数取成功请求的最大值，不重复累加。
          </li>
          <li>
            最近12轮按采集次数排列，不是固定时间轴。空结果表示本轮没有内容；跳过不代表停用。
          </li>
          <li>
            久未采集按上方可选时间阈值判断，与文章发布频率分开。状态是历史记录，不代表此刻在线。
          </li>
          <li>
            内容产出统计为累计值。重点占比以已评分内容为分母，至少20条评分才显示比例；不合成信源质量总分。
          </li>
          <li>
            政策仅存最近一次运行，历史不足处留空。信源配置不可用时，只展示数据库中的记录。
          </li>
        </ul>
        <p className="snapshot-note">
          快照时间 {dateLabel(loadedAt, true)}。刷新不会触发采集。
        </p>
      </section>
    </div>
  )
}
