import { getJournal } from '../../lib/journal-store'
import { PageHeading, DataNotice } from '../journal/Shared'
import { RefreshButton } from '../journal/Actions'
import Predictions from '../journal/Predictions'
export const dynamic = 'force-dynamic'
export default async function PredictionsPage({
  searchParams,
}: {
  searchParams: Promise<{ id?: string }>
}) {
  const { id } = await searchParams,
    data = await getJournal()
  return (
    <>
      <PageHeading
        title="预测与复盘"
        description="保留最初的判断，用后来的证据检验它。"
      >
        <RefreshButton />
      </PageHeading>
      <DataNotice
        issues={data.issues.filter((i) => ['预测', '复盘'].includes(i))}
      />
      <dl className="stat-ribbon">
        <div>
          <dt>全部预测</dt>
          <dd>
            {data.issues.includes('预测') ? '—' : data.predictions.length}
          </dd>
        </div>
        <div>
          <dt>待验证</dt>
          <dd>
            {data.issues.includes('预测')
              ? '—'
              : data.predictions.filter((p) => p.status === 'pending').length}
          </dd>
        </div>
        <div>
          <dt>复盘记录</dt>
          <dd>{data.issues.includes('复盘') ? '—' : data.reviews.length}</dd>
        </div>
        <div>
          <dt>复盘状态</dt>
          <dd style={{ fontSize: 17 }}>
            {data.issues.includes('复盘')
              ? '暂时不可用'
              : data.reviews.length
                ? '已有证据回看'
                : '等待首条复盘'}
          </dd>
          <small>未复盘时不计算命中率</small>
        </div>
      </dl>
      <Predictions
        predictions={data.predictions}
        reviews={data.reviews}
        initialId={id}
      />
    </>
  )
}
