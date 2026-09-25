import { Layers3, Hourglass, CircleCheck } from 'lucide-react'
import { CountLabel, Coverage } from '../journal/Numbers'
import { getJournal } from '../../lib/journal-store'
import { DataNotice } from '../journal/Shared'
import Predictions from '../journal/Predictions'
export const dynamic = 'force-dynamic'
export default async function PredictionsPage({
  searchParams,
}: {
  searchParams: Promise<{ id?: string }>
}) {
  const { id } = await searchParams,
    data = await getJournal()
  const pending = data.predictions.filter((p) => p.status === 'pending').length
  const predictionIds = new Set(data.predictions.map((p) => p.id))
  const reviewed = new Set(
    data.reviews.map((r) => r.prediction_id).filter((id) => predictionIds.has(id)),
  ).size
  const available =
    !data.issues.includes('预测') && !data.issues.includes('复盘')
  return (
    <>
      <Predictions
        predictions={data.predictions}
        reviews={data.reviews}
        initialId={id}
        overview={
          <>
            {' '}
            <DataNotice
              issues={data.issues.filter((i) => ['预测', '复盘'].includes(i))}
            />
            <section
              className="surface prediction-overview"
              aria-label="预测进度"
            >
              <div className="prediction-counts">
                <CountLabel
                  icon={<Layers3 size={17} />}
                  label="预测"
                  value={
                    data.issues.includes('预测') ? '—' : data.predictions.length
                  }
                />
                <CountLabel
                  icon={<Hourglass size={17} />}
                  label="待验证"
                  value={data.issues.includes('预测') ? '—' : pending}
                />
                <CountLabel
                  icon={<CircleCheck size={17} />}
                  label="已复盘"
                  value={available ? reviewed : '—'}
                />
              </div>
              <Coverage
                label="复盘进度"
                value={available ? reviewed : null}
                total={available ? data.predictions.length : null}
                compact
              />
            </section>
          </>
        }
      />
    </>
  )
}
