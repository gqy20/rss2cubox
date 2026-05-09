'use client'

import { useState, useCallback } from 'react'
import type { Dispatch, SetStateAction } from 'react'

export type FilterType = 'all' | 'analyzed' | 'high_value'

export function useFilterState() {
  const [filter, setFilter] = useState<FilterType>('all')
  const [selectedSource, setSelectedSource] = useState<string | null>(null)
  const [selectedTag, setSelectedTag] = useState<string | null>(null)
  const [selectedDateKey, setSelectedDateKey] = useState<string | null>(null)
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({})
  const [dateMenuOpen, setDateMenuOpen] = useState(false)
  const [dateQuery, setDateQuery] = useState('')
  const [loadingMore, setLoadingMore] = useState(false)

  const clearAllFilters = useCallback((setSearch: (v: string) => void) => {
    setSearch('')
    setSelectedSource(null)
    setSelectedTag(null)
    setSelectedDateKey(null)
    setFilter('all')
  }, [])

  return {
    filter,
    setFilter,
    selectedSource,
    setSelectedSource,
    selectedTag,
    setSelectedTag,
    selectedDateKey,
    setSelectedDateKey,
    collapsedGroups,
    setCollapsedGroups,
    dateMenuOpen,
    setDateMenuOpen,
    dateQuery,
    setDateQuery,
    loadingMore,
    setLoadingMore,
    clearAllFilters,
  }
}
