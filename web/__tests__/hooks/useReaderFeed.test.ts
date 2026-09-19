import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest'
import {
  useReaderFeed,
  clearReaderCache,
  rememberReaderScroll,
  readerScroll,
} from '../../hooks/useReaderFeed'
const response = (ids: string[], cursor: string | null = 'next') =>
  ({
    ok: true,
    json: async () => ({
      data: ids.map((id) => ({ id })),
      total: 100,
      page: 1,
      hasMore: Boolean(cursor),
      nextCursor: cursor,
    }),
  }) as Response
beforeEach(() => clearReaderCache())
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})
describe('continuous reader feed', () => {
  it('waits for browser bookmarks, then scopes the read-only request using a POST body', async () => {
    const fetcher = vi.fn().mockResolvedValue(response(['saved'], null))
    vi.stubGlobal('fetch', fetcher)
    const { result, rerender } = renderHook(
      ({ ids }: { ids: string[] | null }) =>
        useReaderFeed<{ id: string }>('signals', 'saved=1', ids),
      { initialProps: { ids: null } as { ids: string[] | null } },
    )
    expect(fetcher).not.toHaveBeenCalled()
    rerender({ ids: ['saved'] })
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(fetcher.mock.calls[0][0]).toBe('/api/reader/signals?saved=1')
    expect(fetcher.mock.calls[0][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ ids: ['saved'] }),
    })
  })

  it('appends once without duplicate rows and preserves the scroll checkpoint', async () => {
    let resolveMore!: (r: Response) => void
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response(['a', 'b']))
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveMore = resolve
          }),
      )
    vi.stubGlobal('fetch', fetcher)
    const { result } = renderHook(() =>
      useReaderFeed<{ id: string }>('signals', 'mode=all'),
    )
    await waitFor(() => expect(result.current.loading).toBe(false))
    rememberReaderScroll(result.current.cacheKey, 456)
    let request!: Promise<void>
    act(() => {
      request = result.current.loadMore()
      void result.current.loadMore()
    })
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(result.current.result?.data.map((r) => r.id)).toEqual(['a', 'b'])
    await act(async () => {
      resolveMore(response(['b', 'c'], null))
      await request
    })
    expect(result.current.result?.data.map((r) => r.id)).toEqual([
      'a',
      'b',
      'c',
    ])
    expect(result.current.result?.hasMore).toBe(false)
    expect(readerScroll(result.current.cacheKey)).toBe(456)
  })
  it('retains the list on append failure and retries the same cursor', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response(['a']))
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(response(['b'], null))
    vi.stubGlobal('fetch', fetcher)
    const { result } = renderHook(() =>
      useReaderFeed<{ id: string }>('signals', ''),
    )
    await waitFor(() => expect(result.current.loading).toBe(false))
    await act(() => result.current.loadMore())
    expect(result.current.moreError).toBe('offline')
    expect(result.current.result?.data).toEqual([{ id: 'a' }])
    await act(() => result.current.loadMore())
    expect(fetcher.mock.calls[1][0]).toBe(fetcher.mock.calls[2][0])
    expect(result.current.result?.data).toEqual([{ id: 'a' }, { id: 'b' }])
  })
  it('restores accumulated rows after remount and only notifies about fresh content', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response(['a']))
      .mockResolvedValueOnce(response(['b'], null))
      .mockResolvedValueOnce(response(['new', 'a']))
    vi.stubGlobal('fetch', fetcher)
    const first = renderHook(() =>
      useReaderFeed<{ id: string }>('policies', 'mode=relevant'),
    )
    await waitFor(() => expect(first.result.current.loading).toBe(false))
    await act(() => first.result.current.loadMore())
    rememberReaderScroll(first.result.current.cacheKey, 200)
    first.unmount()
    const second = renderHook(() =>
      useReaderFeed<{ id: string }>('policies', 'mode=relevant'),
    )
    expect(second.result.current.result?.data).toEqual([
      { id: 'a' },
      { id: 'b' },
    ])
    await waitFor(() => expect(second.result.current.newContent).toBe(true))
    expect(second.result.current.result?.data).toEqual([
      { id: 'a' },
      { id: 'b' },
    ])
    expect(readerScroll(second.result.current.cacheKey)).toBe(200)
  })
  it('discards an in-flight continuation when the filter changes', async () => {
    let resolveOld!: (r: Response) => void
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(response(['old']))
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveOld = resolve
          }),
      )
      .mockResolvedValueOnce(response(['new'], null))
    vi.stubGlobal('fetch', fetcher)
    const { result, rerender } = renderHook(
      ({ query }) => useReaderFeed<{ id: string }>('signals', query),
      { initialProps: { query: 'search=old' } },
    )
    await waitFor(() => expect(result.current.loading).toBe(false))
    let continuation!: Promise<void>
    act(() => {
      continuation = result.current.loadMore()
    })
    rerender({ query: 'search=new' })
    await waitFor(() =>
      expect(result.current.result?.data).toEqual([{ id: 'new' }]),
    )
    await act(async () => {
      resolveOld(response(['late'], null))
      await continuation
    })
    expect(result.current.result?.data).toEqual([{ id: 'new' }])
  })
})
