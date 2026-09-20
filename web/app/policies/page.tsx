import { Coverage } from '../journal/Numbers'
import Reader from '../journal/Reader'
import { PageHeading, DataNotice } from '../journal/Shared'
import {
  policyFacets,
  policyStats,
  readerSourceName,
} from '../../lib/journal-store'
export const dynamic = 'force-dynamic'
export default async function PoliciesPage({
  searchParams,
}: {
  searchParams: Promise<{ sourceRef?: string }>
}) {
  const { sourceRef } = await searchParams
  const sourceLabel =
    typeof sourceRef === 'string'
      ? await readerSourceName(sourceRef).catch(() => null)
      : null
  const [facetResult, statsResult] = await Promise.allSettled([
    policyFacets(),
    policyStats(),
  ])
  const rows = facetResult.status === 'fulfilled' ? facetResult.value : []
  const facets = {
    region: [] as string[],
    stage: [] as string[],
    instrument_type: [] as string[],
    policy_lineage: [] as string[],
  }
  for (const key of ['region', 'stage', 'instrument_type', 'policy_lineage'] as const)
    facets[key] = [
      ...new Set(
        rows.map((r) => r[key]).filter((v): v is string => Boolean(v)),
      ),
    ].sort()
  const stats = statsResult.status === 'fulfilled' ? statsResult.value : null
  return (
    <>
      <PageHeading title="政策观察">
        {stats && (
          <Coverage
            label="政策已析"
            value={stats.analyzed}
            total={stats.total}
            compact
          />
        )}
      </PageHeading>
      <DataNotice
        issues={facetResult.status === 'rejected' ? ['筛选选项'] : []}
      />
      <Reader kind="policies" facets={facets} sourceLabel={sourceLabel} />
    </>
  )
}
