'use client'

import { useState, useCallback } from 'react'
import type { Row } from '../app/types'

export type GroupData = {
  loading: boolean
  loaded: boolean
  items: Row[]
  hasMore: boolean
}

export type GroupPaging = {
  page: number
}

type GroupDataSetter = React.Dispatch<React.SetStateAction<Record<string, GroupData>>>
type GroupPagingSetter = React.Dispatch<React.SetStateAction<Record<string, GroupPaging>>>

export type UseGroupDataOptions = {
  initialGroups?: Record<string, GroupData>
  initialPaging?: Record<string, GroupPaging>
  allDates?: string[]
  groupData?: Record<string, GroupData>
  groupPaging?: Record<string, GroupPaging>
  setGroupData?: GroupDataSetter
  setGroupPaging?: GroupPagingSetter
}

export type UseGroupDataReturn = {
  groupData: Record<string, GroupData>
  groupPaging: Record<string, GroupPaging>
  loadGroupData: (dayKey: string) => Promise<void>
  loadMoreForGroup: (dayKey: string) => Promise<void>
  nextUnloadedDate: string | null
}

export function useGroupData(options: UseGroupDataOptions = {}): UseGroupDataReturn {
  const {
    initialGroups = {},
    initialPaging = {},
    allDates = [],
    setGroupData: externalSetGroupData,
    setGroupPaging: externalSetGroupPaging,
  } = options

  // 支持外部状态注入模式：组件拥有状态时传入 setter，Hook 内部不创建 state
  const [internalGroupData, internalSetGroupData] = useState<Record<string, GroupData>>(initialGroups)
  const [internalGroupPaging, internalSetGroupPaging] = useState<Record<string, GroupPaging>>(initialPaging)

  const groupData = externalSetGroupData ? initialGroups : internalGroupData
  const setGroupData = externalSetGroupData || internalSetGroupData
  const groupPaging = externalSetGroupPaging ? initialPaging : internalGroupPaging
  const setGroupPaging = externalSetGroupPaging || internalSetGroupPaging

  const loadGroupData = useCallback(async (dayKey: string) => {
    const current = groupData[dayKey]
    if (current?.loading || current?.loaded) return

    setGroupData((prev) => ({
      ...prev,
      [dayKey]: { loading: true, loaded: false, items: [], hasMore: false },
    }))

    try {
      const res = await fetch(`/api/signals?page=1&limit=50&date=${dayKey}`)
      const data = await res.json()
      if (!res.ok || !Array.isArray(data.data)) throw new Error(data?.error || 'Invalid response')
      setGroupData((prev) => ({
        ...prev,
        [dayKey]: { loading: false, loaded: true, items: data.data, hasMore: data.hasMore },
      }))
      setGroupPaging((prev) => ({ ...prev, [dayKey]: { page: 1 } }))
    } catch (error) {
      console.error('Failed to load group:', error)
      setGroupData((prev) => ({
        ...prev,
        [dayKey]: { loading: false, loaded: false, items: [], hasMore: false },
      }))
    }
  }, [groupData, setGroupData, setGroupPaging])

  const loadMoreForGroup = useCallback(async (dayKey: string) => {
    const current = groupData[dayKey]
    if (!current?.loaded || current.loading || !current.hasMore) return

    const currentPage = groupPaging[dayKey]?.page || 1
    const nextPage = currentPage + 1

    setGroupData((prev) => ({
      ...prev,
      [dayKey]: { ...(prev[dayKey] || { loaded: true, items: [], hasMore: false }), loading: true },
    }))

    try {
      const res = await fetch(`/api/signals?page=${nextPage}&limit=50&date=${dayKey}`)
      const data = await res.json()
      if (!res.ok || !Array.isArray(data.data)) throw new Error(data?.error || 'Invalid response')

      setGroupData((prev) => {
        const prevItems = prev[dayKey]?.items || []
        return {
          ...prev,
          [dayKey]: { loading: false, loaded: true, items: [...prevItems, ...(data.data as Row[])], hasMore: Boolean(data.hasMore) },
        }
      })
      setGroupPaging((prev) => ({ ...prev, [dayKey]: { page: nextPage } }))
    } catch (error) {
      console.error('Failed to load more group data:', error)
      setGroupData((prev) => ({
        ...prev,
        [dayKey]: { ...(prev[dayKey] || { loaded: true, items: [], hasMore: false }), loading: false },
      }))
    }
  }, [groupData, groupPaging, setGroupData, setGroupPaging])

  const nextUnloadedDate = allDates.length > 0
    ? allDates.find((dayKey) => !groupData[dayKey]?.loaded && !groupData[dayKey]?.loading) ?? null
    : null

  return {
    groupData,
    groupPaging,
    loadGroupData,
    loadMoreForGroup,
    nextUnloadedDate,
  }
}
