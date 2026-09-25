'use client'
import Link from 'next/link'
import type { Prediction, Review } from '../../lib/journal-types'
import { dateLabel } from '../../lib/journal-utils'
import { JsonEvidence } from './Shared'
import { ScoreIndicator } from './Numbers'
import { withOrigin } from '../../lib/reading-context'

const hitLevels: Record<string, string> = {
  exact: '精确命中',
  strong: '强验证',
  partial: '部分命中',
  weak: '弱验证',
  miss: '未命中',
}
/** Full ledger entry: original judgment, expected evidence, falsifiers and
 *  every review. Rendered inside the predictions drawer. */
export default function PredictionDetail({
  prediction,
  reviews,
  from,
}: {
  prediction: Prediction
  reviews: Review[]
  from: string
}) {
  return (
    <>
      <div className="document-section">
        <h3>原始判断</h3>
        <p>{prediction.prediction_body}</p>
      </div>
      <div className="document-section">
        <h3>预期验证证据</h3>
        <JsonEvidence value={prediction.expected_evidence} />
      </div>
      <div className="document-section">
        <h3>什么会推翻这个判断</h3>
        <p>{prediction.disconfirming_evidence || '未记录反证条件'}</p>
      </div>
      {prediction.signal_cluster_id && (
        <Link
          className="text-link"
          href={withOrigin(`/topics?id=${prediction.signal_cluster_id}`, from)}
        >
          阅读关联专题 →
        </Link>
      )}
      {reviews.length ? (
        reviews.map((review) => (
          <section className="review-note" key={review.id}>
            <div className="metadata">
              复盘于 {dateLabel(review.reviewed_at, true)}
              <ScoreIndicator label="复盘评分" value={review.score} />
              <span>{hitLevels[review.hit_level] || review.hit_level}</span>
            </div>
            <p>{review.actual_observation}</p>
            <p>{review.why_score}</p>
            {review.improvement_advice && (
              <p>
                <strong>改进建议：</strong>
                {review.improvement_advice}
              </p>
            )}
            <details className="disclosure">
              <summary>支持与反对材料</summary>
              <div>
                <h3>支持材料</h3>
                <JsonEvidence value={review.supporting_articles} />
                <h3>反对材料</h3>
                <JsonEvidence value={review.contradicting_articles} />
              </div>
            </details>
          </section>
        ))
      ) : (
        <p className="snapshot-note">
          这条判断尚无复盘记录。待验证不代表已经发生或已经命中。
        </p>
      )}
    </>
  )
}
