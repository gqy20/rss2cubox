import Reader from '../journal/Reader'
import { PageHeading } from '../journal/Shared'
import {
  signalSources,
  topicName,
  readerSourceName,
} from '../../lib/journal-store'
export const dynamic = 'force-dynamic'
export default async function SignalsPage({
  searchParams,
}: {
  searchParams: Promise<{ topic?: string; sourceRef?: string }>
}) {
  const { topic, sourceRef } = await searchParams
  const [sources, label, sourceLabel] = await Promise.all([
    signalSources().catch(() => []),
    typeof topic === 'string'
      ? topicName(topic).catch(() => null)
      : Promise.resolve(null),
    typeof sourceRef === 'string'
      ? readerSourceName(sourceRef).catch(() => null)
      : Promise.resolve(null),
  ])
  return (
    <>
      <PageHeading title="技术信号" />
      <Reader
        kind="signals"
        sources={sources.map((s) => s.source)}
        topicLabel={label}
        sourceLabel={sourceLabel}
      />
    </>
  )
}
