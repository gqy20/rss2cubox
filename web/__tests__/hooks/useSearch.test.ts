import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useSearch } from '@/hooks/useSearch'

// Mock fetch globally for search API calls
const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

describe('useSearch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('should return empty initial state', () => {
    const { result } = renderHook(() => useSearch())
    expect(result.current.search).toBe('')
    expect(result.current.debouncedSearch).toBe('')
    expect(result.current.searchRows).toEqual([])
    expect(result.current.searchLoading).toBe(false)
    expect(result.current.isSearchMode).toBe(false)
  })

  it('should update search value immediately on change', () => {
    const { result } = renderHook(() => useSearch())
    act(() => { result.current.setSearch('test') })
    expect(result.current.search).toBe('test')
  })

  it('should debounce search value (280ms)', async () => {
    const { result } = renderHook(() => useSearch())
    act(() => { result.current.setSearch('hello') })
    // Should not be debounced yet
    expect(result.current.debouncedSearch).toBe('')
    // Advance past debounce delay
    act(() => { vi.advanceTimersByTime(300) })
    expect(result.current.debouncedSearch).toBe('hello')
  })

  it('should clear debounced search when input is cleared', async () => {
    const { result } = renderHook(() => useSearch())
    act(() => { result.current.setSearch('test') })
    act(() => { vi.advanceTimersByTime(300) })
    expect(result.current.debouncedSearch).toBe('test')
    act(() => { result.current.setSearch('') })
    act(() => { vi.advanceTimersByTime(300) })
    expect(result.current.debouncedSearch).toBe('')
  })

  it('should indicate search mode when query is non-empty', () => {
    const { result } = renderHook(() => useSearch())
    expect(result.current.isSearchMode).toBe(false)
    act(() => { result.current.setSearch('something') })
    expect(result.current.isSearchMode).toBe(true)
  })

  it('should fetch results when debounced search changes', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        data: [{ id: 1, title: 'Result 1' }],
        total: 1,
        hasMore: false,
      }),
    })

    const { result } = renderHook(() => useSearch())

    act(() => { result.current.setSearch('query') })
    act(() => { vi.advanceTimersByTime(300) })

    // Switch to real timers so async fetch can resolve
    vi.useRealTimers()
    await vi.waitFor(() => {
      expect(result.current.searchRows).toHaveLength(1)
    }, { timeout: 2000 })

    expect(mockFetch).toHaveBeenCalled()
    expect(result.current.searchTotal).toBe(1)
  })

  it('should support loading more pages', async () => {
    // First page
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        data: Array.from({ length: 50 }, (_, i) => ({ id: i })),
        total: 120,
        hasMore: true,
      }),
    })
    // Second page
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        data: Array.from({ length: 50 }, (_, i) => ({ id: 50 + i })),
        total: 120,
        hasMore: true,
      }),
    })

    const { result } = renderHook(() => useSearch({ pageSize: 50 }))

    act(() => { result.current.setSearch('test') })
    act(() => { vi.advanceTimersByTime(300) })

    vi.useRealTimers()
    await vi.waitFor(() => expect(result.current.searchLoading).toBe(false), { timeout: 2000 })

    expect(result.current.searchRows).toHaveLength(50)

    // Load more
    await act(async () => { await result.current.fetchSearchPage(2, true) })
    expect(result.current.searchRows).toHaveLength(100)
  })

  it('should abort previous request on new search', async () => {
    let abortCalled = false
    let resolveFirstFetch: (() => void) | undefined

    mockFetch.mockImplementation((_url: string, options?: RequestInit) => {
      if (options?.signal) {
        options.signal.addEventListener('abort', () => { abortCalled = true })
      }
      // First fetch call hangs so we can abort it before it resolves
      if (mockFetch.mock.calls.length === 1) {
        return new Promise((resolve) => {
          resolveFirstFetch = () => resolve({
            ok: true,
            json: async () => ({ data: [], total: 0, hasMore: false }),
          })
        })
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({ data: [], total: 0, hasMore: false }),
      })
    })

    const { result } = renderHook(() => useSearch())

    // Trigger first search and let debounce fire (fetch will hang)
    act(() => { result.current.setSearch('first') })
    act(() => { vi.advanceTimersByTime(300) })

    // Change search before first fetch completes → should abort first request
    act(() => { result.current.setSearch('second') })
    act(() => { vi.advanceTimersByTime(300) })

    vi.useRealTimers()
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10))
    })

    expect(mockFetch.mock.calls.length).toBeGreaterThanOrEqual(1)
    expect(abortCalled).toBe(true)
  })
})
