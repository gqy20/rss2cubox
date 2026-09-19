import Reader from '../journal/Reader'
import { PageHeading, DataNotice } from '../journal/Shared'
import { policyFacets, policyStats } from '../../lib/journal-store'
export const dynamic = 'force-dynamic'
export default async function PoliciesPage({
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
  const [facetResult, statsResult] = await Promise.allSettled([
    policyFacets(),
    policyStats(),
  ])
  const rows = facetResult.status === 'fulfilled' ? facetResult.value : []
  const facets = {
    region: [] as string[],
    stage: [] as string[],
    instrument_type: [] as string[],
  }
  for (const key of ['region', 'stage', 'instrument_type'] as const)
    facets[key] = [
      ...new Set(
        rows.map((r) => r[key]).filter((v): v is string => Boolean(v)),
      ),
    ].sort()
  const stats = statsResult.status === 'fulfilled' ? statsResult.value : null
  return (
    <>
      <PageHeading
        title="政策观察"
        description="分清文件性质、适用范围与阶段，再判断它意味着什么。"
      >
        {stats && (
          <span className="muted-text">
            已收录 {stats.total} 份 · 已分析 {stats.analyzed} 份
          </span>
        )}
      </PageHeading>
      <DataNotice
        issues={facetResult.status === 'rejected' ? ['筛选选项'] : []}
      />
      <Reader
        key={JSON.stringify(initial)}
        kind="policies"
        initial={initial}
        initialId={initial.id}
        facets={facets}
      />
    </>
  )
}
