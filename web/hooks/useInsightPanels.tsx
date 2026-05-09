'use client'

import { useState, useEffect, useMemo } from 'react'
import { TrendingUp, Radio, Lightbulb } from 'lucide-react'
import { loadAllGlobalInsights, type InsightHistoryItem } from '../lib/signalStore'
import type { GlobalInsights, InsightKey } from '../app/types'
import type { ParsedInsightItem, InsightPanel } from '../app/DashboardSections'

const { parseInsightString, normalizeInsightItems } = (() => {
  function parseInsightString(raw: string): ParsedInsightItem {
    const text = raw.trim()
    if (!text) return { title: '' }

    const titleMatch = text.match(/["']title["']\s*:\s*["']([\s\S]*?)["']\s*(,|})/)
    const contentMatch = text.match(/["']content["']\s*:\s*["']([\s\S]*?)["']\s*(,|})/)

    if (titleMatch?.[1]) {
      const title = titleMatch[1].trim()
      const content = contentMatch?.[1]?.trim()
      return { title, content }
    }

    const pyContentMatch = text.match(/['"]content['"]\s*:\s*['"]([\s\S]*?)['"]\s*(,|})/)
    if (pyContentMatch?.[1]) {
      return { title: pyContentMatch[1].trim() }
    }

    return { title: text }
  }

  function normalizeInsightItems(items: unknown[]): ParsedInsightItem[] {
    if (!Array.isArray(items)) return []
    return items
      .map((item): ParsedInsightItem | null => {
        if (item && typeof item === 'object' && !Array.isArray(item)) {
          const obj = item as Record<string, unknown>
          if ('text' in obj && typeof obj.text === 'string') {
            const text = obj.text.trim()
            if (!text) return null
            const urls = Array.isArray(obj.source_urls)
              ? obj.source_urls.filter((u): u is string => typeof u === 'string' && Boolean(u.trim()))
              : []
            const titles = Array.isArray(obj.source_titles)
              ? obj.source_titles.filter((t): t is string => typeof t === 'string' && Boolean(t.trim()))
              : []
            return { title: text, content: undefined, sourceUrls: urls, sourceTitles: titles }
          }
          const title = String(obj.title ?? '').trim()
          const content = String(obj.content ?? '').trim()
          if (title) return { title, content: content || undefined }
          if (content) return { title: content }
          return null
        }
        if (typeof item === 'string') return parseInsightString(item)
        return { title: String(item ?? '').trim() }
      })
      .filter((item): item is ParsedInsightItem => item !== null && item.title.length > 0)
  }

  return { parseInsightString, normalizeInsightItems }
})()

export { normalizeInsightItems }

type UseInsightPanelsProps = {
  insights?: GlobalInsights | null
}

export function useInsightPanels({ insights }: UseInsightPanelsProps) {
  const [insightsHistory, setInsightsHistory] = useState<InsightHistoryItem[]>([])
  const [selectedInsightIdx, setSelectedInsightIdx] = useState<number>(0)
  const [selectedInsightKey, setSelectedInsightKey] = useState<InsightKey>('daily_advices')

  useEffect(() => {
    loadAllGlobalInsights(30)
      .then((history) => {
        setInsightsHistory(history)
        if (history.length > 0) setSelectedInsightIdx(0)
      })
      .catch(() => console.error('Failed to load insights history'))
  }, [])

  const currentInsights = insightsHistory[selectedInsightIdx]?.data ?? insights ?? null

  const insightPanels: InsightPanel[] = useMemo(
    () => [
      { key: 'trends' as InsightKey, title: '宏观技术趋势', icon: <TrendingUp size={16} color="#2dd4bf" />, items: normalizeInsightItems(Array.isArray(currentInsights?.trends) ? currentInsights.trends : []) },
      { key: 'weak_signals' as InsightKey, title: '暗流弱信号', icon: <Radio size={16} color="#f59e0b" />, items: normalizeInsightItems(Array.isArray(currentInsights?.weak_signals) ? currentInsights.weak_signals : []) },
      { key: 'daily_advices' as InsightKey, title: '今日行动建议', icon: <Lightbulb size={16} color="#a78bfa" />, items: normalizeInsightItems(Array.isArray(currentInsights?.daily_advices) ? currentInsights.daily_advices : []) },
    ],
    [currentInsights],
  )

  const visibleInsightPanels = useMemo(
    () => insightPanels.filter((panel) => panel.items.length > 0),
    [insightPanels],
  )

  const activeInsightPanel = useMemo(
    () => visibleInsightPanels.find((panel) => panel.key === selectedInsightKey) ?? visibleInsightPanels[0],
    [selectedInsightKey, visibleInsightPanels],
  )

  return {
    insightsHistory,
    selectedInsightIdx,
    setSelectedInsightIdx,
    selectedInsightKey,
    setSelectedInsightKey,
    insightPanels,
    visibleInsightPanels,
    activeInsightPanel,
  }
}
