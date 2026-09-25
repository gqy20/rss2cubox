import { Coverage } from '../journal/Numbers'
import Reader from '../journal/Reader'
import { PageHeading, DataNotice } from '../journal/Shared'
import LineageStrip from './LineageStrip'
import {
  policyFacets,
  policyLineageStats,
  policyStats,
  readerSourceName,
} from '../../lib/journal-store'
export const dynamic = 'force-dynamic'
export default async function PoliciesPage({
  searchParams,
}: {
  searchParams: Promise<{ sourceRef?: string; policy_lineage?: string }>
}) {
  const { sourceRef, policy_lineage: lineage } = await searchParams
  const selected =
    typeof lineage === 'string' ? lineage.slice(0, 60) : ''
  const sourceLabel =
    typeof sourceRef === 'string'
      ? await readerSourceName(sourceRef).catch(() => null)
      : null
  const [facetResult, statsResult, lineageResult] = await Promise.allSettled([
    policyFacets(),
    policyStats(),
    policyLineageStats(selected),
  ])
  const facets =
    facetResult.status === 'fulfilled'
      ? facetResult.value
      : {
          region: [] as string[],
          stage: [] as string[],
          instrument_type: [] as string[],
          policy_lineage: [] as string[],
        }
  const stats = statsResult.status === 'fulfilled' ? statsResult.value : null
  return (
    <>
      <PageHeading title="政策观察" />
      <DataNotice
        issues={
          [
            facetResult.status === 'rejected' ? '筛选选项' : '',
            lineageResult.status === 'rejected' ? '主线统计' : '',
          ].filter(Boolean) as string[]
        }
      />
      {lineageResult.status === 'fulfilled' && (
        <LineageStrip stats={lineageResult.value} selected={selected} />
      )}
      <Reader
        kind="policies"
        facets={facets}
        sourceLabel={sourceLabel}
        toolbarAside={
          stats && (
            <Coverage
              label="政策已析"
              value={stats.analyzed}
              total={stats.total}
              compact
            />
          )
        }
      />
    </>
  )
}
