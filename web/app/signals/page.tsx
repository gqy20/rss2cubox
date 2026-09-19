import Reader from '../journal/Reader'
import { PageHeading } from '../journal/Shared'
import { signalSources } from '../../lib/journal-store'
export const dynamic = 'force-dynamic'
export default async function SignalsPage() {
  const sources = await signalSources().catch(() => [])
  return (
    <>
      <PageHeading title="技术信号" />
      <Reader kind="signals" sources={sources.map((s) => s.source)} />
    </>
  )
}
