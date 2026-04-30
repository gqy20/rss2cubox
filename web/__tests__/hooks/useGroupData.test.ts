import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useGroupData } from '@/hooks/useGroupData'

const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

describe('useGroupData', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should initialize with empty state', () => {
    const { result } = renderHook(() => useGroupData())
    expect(result.current.groupData).toEqual({})
    expect(result.current.groupPaging).toEqual({})
  })

  it('should initialize with provided initial data', () => {
    const { result } = renderHook(() =>
      useGroupData({
        initialGroups: {
          '2025-06-01': { loading: false, loaded: true, items: [{ id: '1' } as any], hasMore: true },
        },
        initialPaging: { '2025-06-01': { page: 1 } },
      })
    )
    expect(result.current.groupData['2025-06-01'].loaded).toBe(true)
    expect(result.current.groupData['2025-06-01'].items).toHaveLength(1)
  })

  it('should load group data on demand', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        data: [{ id: 10 }, { id: 11 }],
        total: 5,
        hasMore: true,
      }),
    })

    const { result } = renderHook(() => useGroupData())

    await act(async () => { await result.current.loadGroupData('2025-05-20') })

    expect(result.current.groupData['2025-05-20'].loaded).toBe(true)
    expect(result.current.groupData['2025-05-20'].items).toHaveLength(2)
    expect(result.current.groupData['2025-05-20'].hasMore).toBe(true)
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/signals?page=1&limit=50&date=2025-05-20',
      { cache: 'no-store' },
    )
  })

  it('uses externally controlled group state when provided', async () => {
    const setGroupData = vi.fn()
    const setGroupPaging = vi.fn()

    const { result } = renderHook(() =>
      useGroupData({
        groupData: {
          '2025-06-01': { loading: false, loaded: true, items: [], hasMore: false },
        },
        groupPaging: { '2025-06-01': { page: 1 } },
        setGroupData,
        setGroupPaging,
      })
    )

    await act(async () => { await result.current.loadGroupData('2025-06-01') })

    expect(mockFetch).not.toHaveBeenCalled()
    expect(setGroupData).not.toHaveBeenCalled()
    expect(setGroupPaging).not.toHaveBeenCalled()
  })

  it('should not reload already loaded group', async () => {
    const { result } = renderHook(() =>
      useGroupData({
        initialGroups: {
          '2025-06-01': { loading: false, loaded: true, items: [], hasMore: false },
        },
        initialPaging: { '2025-06-01': { page: 1 } },
      })
    )

    await act(async () => { await result.current.loadGroupData('2025-06-01') })
    // Should not call fetch since already loaded
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('should load more items for a group (pagination)', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        data: [{ id: 3 }, { id: 4 }],
        total: 6,
        hasMore: false,
      }),
    })

    const { result } = renderHook(() =>
      useGroupData({
        initialGroups: {
          '2025-06-01': { loading: false, loaded: true, items: [{ id: 1 }, { id: 2 }] as any, hasMore: true },
        },
        initialPaging: { '2025-06-01': { page: 1 } },
      })
    )

    await act(async () => { await result.current.loadMoreForGroup('2025-06-01') })

    expect(result.current.groupData['2025-06-01'].items).toHaveLength(4)
    expect(result.current.groupPaging['2025-06-01'].page).toBe(2)
  })

  it('should find next unloaded date', () => {
    const { result } = renderHook(() =>
      useGroupData({
        allDates: ['2025-06-03', '2025-06-02', '2025-06-01'],
        initialGroups: {
          '2025-06-03': { loading: false, loaded: true, items: [], hasMore: false },
        },
        initialPaging: {},
      })
    )
    expect(result.current.nextUnloadedDate).toBe('2025-06-02')
  })

  it('should return null for nextUnloadedDate when all loaded', () => {
    const { result } = renderHook(() =>
      useGroupData({
        allDates: ['2025-06-01'],
        initialGroups: {
          '2025-06-01': { loading: false, loaded: true, items: [], hasMore: false },
        },
        initialPaging: {},
      })
    )
    expect(result.current.nextUnloadedDate).toBeNull()
  })
})
