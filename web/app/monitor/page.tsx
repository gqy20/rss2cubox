import { BookOpen, Rss, Activity, CircleCheck, CircleAlert } from 'lucide-react'
import { Coverage, CountLabel } from '../journal/Numbers'
import {
  getJournal,
  sourceHealth,
  collectionTrend,
} from '../../lib/journal-store'
import { dateLabel, healthStatus } from '../../lib/journal-utils'
import { PageHeading, PanelHeading, DataNotice, Empty } from '../journal/Shared'
import { RefreshButton } from '../journal/Actions'
import TrendChart from '../journal/TrendChart'
export const dynamic = 'force-dynamic'
export default async function MonitorPage() {
  const [data, health, trend] = await Promise.all([
    getJournal(),
    sourceHealth(),
    collectionTrend().catch(() => null),
  ])
  const now = Date.now(),
    recent = health.sources.filter(
      (s) => s.last_run && now - new Date(s.last_run).getTime() < 86400000,
    )
  const failed = recent.filter((s) =>
    ['failed', 'timeout', 'parse_error'].includes(s.status),
  ).length
  return (
    <>
      <PageHeading
        title="运行监控"
        description="了解数据从哪里来、何时更新，以及哪些来源需要关注。"
      >
        <RefreshButton />
      </PageHeading>
      <DataNotice
        issues={[
          ...data.issues.filter((i) => ['文章统计', '政策统计'].includes(i)),
          ...health.issues,
          ...(trend ? [] : ['采集趋势']),
        ]}
      />
      <section className="metric-strip" aria-label="运行概况">
        <div>
          <CountLabel
            icon={<BookOpen size={17} />}
            label="文章"
            value={data.stats?.total ?? '—'}
          />
          <span className="metric-secondary">
            <Rss size={12} aria-hidden="true" />
            {data.stats?.sources ?? '—'} 来源
          </span>
        </div>
        <div>
          <Coverage
            label="政策已析"
            value={data.policyStats?.analyzed}
            total={data.policyStats?.total}
            compact
          />
        </div>
        <div>
          <CountLabel
            icon={<Activity size={17} />}
            label="24h 采集来源"
            value={health.issues.length ? '—' : recent.length}
          />
        </div>
        <div className={failed ? 'metric-alert' : ''}>
          <CountLabel
            icon={
              failed ? <CircleAlert size={17} /> : <CircleCheck size={17} />
            }
            label="24h 失败来源"
            value={health.issues.length ? '—' : failed || '无'}
          />
        </div>
      </section>
      <div className="monitor-grid">
        <section className="surface">
          <PanelHeading title="近两周入库变化" />
          {trend ? (
            <TrendChart data={trend} />
          ) : (
            <Empty title="趋势暂时不可用" />
          )}
        </section>
        <section className="surface">
          <PanelHeading title="数据准备情况" />
          <Coverage
            label="文章已析"
            value={data.stats?.analyzed}
            total={data.stats?.total}
          />
          <Coverage
            label="政策已析"
            value={data.policyStats?.analyzed}
            total={data.policyStats?.total}
          />
          <details className="metric-definition">
            <summary>统计口径</summary>
            <p>
              文章分析以隐藏信号、判断依据或行动建议非空为准。政策预筛会跳过低相关文件，未分析数量不等同于待处理队列。24h
              来源统计取各来源最近一次采集记录；失败包括超时、采集失败和解析错误。
            </p>
          </details>
          <div className="document-section">
            <h3>最近的数据时间</h3>
            <div className="metadata">
              文章入库 {dateLabel(data.stats?.latest, true)}
            </div>
            <div className="metadata">
              全局洞察 {dateLabel(data.insights?.generated_at, true)}
            </div>
          </div>
        </section>
      </div>
      <section className="surface">
        <PanelHeading title="信源最近一次采集" />
        <p className="panel-intro">
          科技来源最多展示最近300个；状态是历史运行结果，不代表当前在线状态。
        </p>
        {health.sources.length ? (
          <div className="table-scroll">
            <table className="health-table">
              <thead>
                <tr>
                  <th>信源</th>
                  <th>类型</th>
                  <th>最近运行</th>
                  <th>结果</th>
                  <th>获取条数</th>
                  <th>耗时</th>
                </tr>
              </thead>
              <tbody>
                {health.sources.map((s, i) => (
                  <tr key={`${s.kind}:${s.name}:${i}`}>
                    <td>{s.name}</td>
                    <td>{s.kind}</td>
                    <td>
                      {dateLabel(s.last_run, true)}
                      {s.last_run &&
                        now - new Date(s.last_run).getTime() > 86400000 && (
                          <small className="timestamp">超过24小时无更新</small>
                        )}
                    </td>
                    <td>
                      <span
                        className={`health-status ${['ok', 'success'].includes(s.status) ? 'ok' : ['failed', 'timeout', 'parse_error'].includes(s.status) ? 'error' : ''}`}
                      >
                        {healthStatus[s.status] || s.status || '未记录'}
                      </span>
                      {Boolean(s.empty_runs) && (
                        <small className="timestamp">
                          连续空跑 {s.empty_runs} 次
                        </small>
                      )}
                    </td>
                    <td>{s.fetched ?? '—'}</td>
                    <td>
                      {s.duration_ms == null
                        ? '—'
                        : `${(s.duration_ms / 1000).toFixed(1)}s`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="暂无采集运行记录"
            description="流水线写入信源运行记录后，会显示各来源的采集结果。"
          />
        )}
      </section>
      <p className="snapshot-note">
        本页数据读取于 {dateLabel(data.loadedAt, true)}
        。刷新只重新读取数据，不触发采集或模型调用。
      </p>
    </>
  )
}
