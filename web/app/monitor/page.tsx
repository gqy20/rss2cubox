import { readMonitorSnapshot } from '../../lib/monitor-store'
import {
  articleStats,
  policyStats,
  collectionTrend,
} from '../../lib/journal-store'
import { PageHeading, DataNotice } from '../journal/Shared'
import { RefreshButton } from '../journal/Actions'
import { SearchTrigger } from '../journal/SearchPalette'
import SourceMonitor from '../journal/SourceMonitor'
export const dynamic = 'force-dynamic'
export default async function MonitorPage() {
  const [snapshot, articles, policies, trend] = await Promise.all([
    readMonitorSnapshot(),
    articleStats().catch(() => null),
    policyStats().catch(() => null),
    collectionTrend().catch(() => null),
  ])
  return (
    <>
      <PageHeading title="运行监控" />
      <DataNotice issues={snapshot.issues} />
      <SourceMonitor
        snapshot={snapshot}
        stats={articles}
        policyStats={policies}
        trend={trend}
        actions={
          <>
            <SearchTrigger />
            <RefreshButton />
          </>
        }
      />
    </>
  )
}
