'use client'

import { useState, useMemo, useEffect, useCallback } from 'react'
import type { Metrics } from '../app/types'
import type { LocalStats } from '../lib/signalStore'

const LIVE_REFRESH_INTERVAL_MS = 60_000

function statsToMetrics(stats: LocalStats, previous: Metrics): Metrics {
  return {
    ...previous,
    generated_at: new Date().toISOString(),
    signals_total: stats.total,
    exported_total: stats.total,
    active_sources_total: stats.sources,
    top_source_counts: stats.topSourceCounts ?? previous.top_source_counts,
    total_all: stats.total,
    analyzed_total: stats.analyzed,
    total_today: stats.today,
    total_yesterday: stats.yesterday,
    analyzed_today: stats.analyzedToday,
    analyzed_yesterday: stats.analyzedYesterday,
    sources_today: stats.sourcesToday,
    sources_yesterday: stats.sourcesYesterday,
    timeline_points: stats.trendData ?? previous.timeline_points,
    daily_totals: stats.dailyTotals ?? previous.daily_totals,
  }
}

type UseDashboardMetricsProps = {
  initialMetrics: Metrics
  serverTime?: string
}

export function useDashboardMetrics({ initialMetrics, serverTime }: UseDashboardMetricsProps) {
  const [metrics, setMetrics] = useState<Metrics>(initialMetrics)
  const [now, setNow] = useState<Date | null>(serverTime ? new Date(serverTime) : null)

  const formatGeneratedAt = (value?: string) => {
    if (!value) return '未知'
    const dt = new Date(value)
    if (Number.isNaN(dt.getTime())) return '未知'
    return dt.toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  }

  useEffect(() => {
    setNow(new Date())
    const timer = setInterval(() => setNow(new Date()), 60000)
    return () => clearInterval(timer)
  }, [])

  const todayKey = useMemo(() => {
    const d = now ?? new Date()
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  }, [now])

  const yesterdayKey = useMemo(() => {
    const d = new Date(now ?? new Date())
    d.setDate(d.getDate() - 1)
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  }, [now])

  const refreshDashboardData = useCallback(async () => {
    try {
      const res = await fetch('/api/signals/local/stats', { cache: 'no-store' })
      if (res.ok) {
        const stats = await res.json() as LocalStats
        setMetrics((prev) => statsToMetrics(stats, prev))
      }
    } catch (error) {
      console.error('Failed to refresh dashboard metrics:', error)
    }
  }, [])

  useEffect(() => {
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') void refreshDashboardData()
    }, LIVE_REFRESH_INTERVAL_MS)

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') void refreshDashboardData()
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [refreshDashboardData])

  return {
    metrics,
    setMetrics,
    now,
    todayKey,
    yesterdayKey,
    formatGeneratedAt,
    refreshDashboardData,
  }
}
