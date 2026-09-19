import Reader from '../journal/Reader'
import { PageHeading } from '../journal/Shared'
import { signalSources } from '../../lib/journal-store'
export const dynamic = 'force-dynamic'
export default async function SignalsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}) {
  const params = await searchParams
  const initial = Object.fromEntries(
    Object.entries(params).filter(
      (entry): entry is [string, string] => typeof entry[1] === 'string',
    ),
  )
  const sources = await signalSources().catch(() => [])
  return (
    <>
      <PageHeading
        title="技术信号"
        description="把值得关注的变化，留给更深入的阅读。"
      />
      <Reader
        key={JSON.stringify(initial)}
        kind="signals"
        initial={initial}
        initialId={initial.id}
        sources={sources.map((s) => s.source)}
      />
    </>
  )
}
