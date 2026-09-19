import type { Row } from '../app/types'
import type { Policy } from './journal-types'
export type SourceKind = 'tech' | 'policy'
export type RunStatus = 'ok' | 'failed' | 'empty' | 'skipped'
export type MonitorStatus =
  RunStatus | 'never' | 'disabled' | 'archived' | 'unavailable'
export type SourceRun = {
  id: string
  at: string
  status: RunStatus
  fetched: number
  durationMs: number
  attempts: number
  error: string | null
}
export type MonitorSource = {
  id: string
  name: string
  kind: SourceKind
  domain: string
  address: string
  configuration: 'enabled' | 'disabled' | 'historical' | 'unknown'
  status: MonitorStatus
  runs: SourceRun[]
  lastRun: string | null
  lastSuccess: string | null
  lastPublished: string | null
  failureStreak: number
  emptyStreak: number
  recovered: boolean
  articles: number
  analyzed: number
  scored: number
  high: number
  region?: string
  contentAvailable: boolean
}
export type MonitorSnapshot = {
  sources: MonitorSource[]
  issues: string[]
  loadedAt: string
}
export type SourceAttempt = {
  runId: string
  at: string
  status: string
  address: string
  durationMs: number
  error: string | null
}
export type MonitorDetail = {
  articles: Row[]
  highArticles: Row[]
  policies: Policy[]
  highPolicies: Policy[]
  topics: { id: number; label: string; articles: number }[]
  attempts: SourceAttempt[]
  issues: string[]
}
export type SourceSpec = {
  kind: SourceKind
  key: string
  name: string
  url: string
  enabled: boolean
  region?: string
}
