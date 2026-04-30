'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import type { Row } from '../app/types'

const DEFAULT_PAGE_SIZE = 50

export type UseSearchOptions = {
  pageSize?: number
}

export type UseSearchReturn = {
  search: string
  debouncedSearch: string
  searchRows: Row[]
  searchPage: number
  searchTotal: number
  searchHasMore: boolean
  searchLoading: boolean
  isSearchMode: boolean
  setSearch: (value: string) => void
  fetchSearchPage: (page: number, append: boolean) => Promise<void>
}

export function useSearch(options: UseSearchOptions = {}): UseSearchReturn {
  const { pageSize = DEFAULT_PAGE_SIZE } = options

  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [searchRows, setSearchRows] = useState<Row[]>([])
  const [searchPage, setSearchPage] = useState(1)
  const [searchTotal, setSearchTotal] = useState(0)
  const [searchHasMore, setSearchHasMore] = useState(false)
  const [searchLoading, setSearchLoading] = useState(false)
  const searchAbortRef = useRef<AbortController | null>(null)

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search.trim()), 280)
    return () => clearTimeout(timer)
  }, [search])

  // Clear state when search empties
  useEffect(() => {
    if (!debouncedSearch.trim()) {
      searchAbortRef.current?.abort()
      setSearchRows([])
      setSearchPage(1)
      setSearchTotal(0)
      setSearchHasMore(false)
      setSearchLoading(false)
      return
    }
  }, [debouncedSearch])

  const fetchSearchPage = useCallback(async (page: number, append: boolean) => {
    const keyword = debouncedSearch.trim()
    if (!keyword) return

    searchAbortRef.current?.abort()
    const controller = new AbortController()
    searchAbortRef.current = controller

    if (append) setSearchLoading(true)
    else setSearchLoading(true)

    try {
      const res = await fetch(
        `/api/signals?page=${page}&limit=${pageSize}&search=${encodeURIComponent(keyword)}`,
        { signal: controller.signal, cache: 'no-store' },
      )
      const data = await res.json()
      if (!res.ok || !Array.isArray(data.data)) throw new Error(data?.error || 'Invalid response')

      const rows = data.data as Row[]
      setSearchRows((prev) => (append ? [...prev, ...rows] : rows))
      setSearchPage(page)
      setSearchTotal(Number(data.total || 0))
      setSearchHasMore(Boolean(data.hasMore))
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') return
      console.error('Failed to search signals:', error)
      if (!append) {
        setSearchRows([])
        setSearchTotal(0)
      }
      setSearchHasMore(false)
    } finally {
      setSearchLoading(false)
    }
  }, [debouncedSearch, pageSize])

  // Auto-fetch when debounced search changes
  useEffect(() => {
    if (!debouncedSearch.trim()) return
    void fetchSearchPage(1, false)
  }, [debouncedSearch, fetchSearchPage])

  // Cleanup abort on unmount
  useEffect(() => {
    return () => { searchAbortRef.current?.abort() }
  }, [])

  const isSearchMode = search.trim().length > 0

  return {
    search,
    debouncedSearch,
    searchRows,
    searchPage,
    searchTotal,
    searchHasMore,
    searchLoading,
    isSearchMode,
    setSearch,
    fetchSearchPage,
  }
}
