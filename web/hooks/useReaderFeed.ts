'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { PageResult } from '../lib/journal-types'

type Item = { id: string }
type Entry = { result: PageResult<Item>; scrollTop: number }
const cache = new Map<string, Entry>()
const MAX_CACHED_QUERIES = 6
function remember<T extends Item>(key: string, result: PageResult<T>) {
  const scrollTop = cache.get(key)?.scrollTop || 0
  cache.delete(key)
  cache.set(key, { result, scrollTop })
  while (cache.size > MAX_CACHED_QUERIES)
    cache.delete(cache.keys().next().value!)
}
export function rememberReaderScroll(key: string, scrollTop: number) {
  const entry = cache.get(key)
  if (entry) entry.scrollTop = scrollTop
}
export function readerScroll(key: string) {
  return cache.get(key)?.scrollTop || 0
}
export function clearReaderCache() {
  cache.clear()
}
export function mergeReaderRows<T extends Item>(previous: T[], next: T[]) {
  const seen = new Set(previous.map((r) => r.id))
  return [
    ...previous,
    ...next.filter((r) => {
      if (seen.has(r.id)) return false
      seen.add(r.id)
      return true
    }),
  ]
}
type State<T> = {
  key: string
  result: PageResult<T> | null
  loading: boolean
  loadingMore: boolean
  error: string
  moreError: string
  newContent: boolean
}
const empty = <T>(key: string): State<T> => ({
  key,
  result: null,
  loading: true,
  loadingMore: false,
  error: '',
  moreError: '',
  newContent: false,
})
async function request<T>(
  url: string,
  signal: AbortSignal,
): Promise<PageResult<T>> {
  const response = await fetch(url, { signal, cache: 'no-store' }),
    body = await response.json()
  if (!response.ok) throw new Error(body.error || '加载失败，请重试')
  if (
    !Array.isArray(body.data) ||
    typeof body.total !== 'number' ||
    (body.hasMore && !body.nextCursor)
  )
    throw new Error('加载位置不可用，请刷新列表')
  return body
}
export function useReaderFeed<T extends Item>(kind: string, encoded: string) {
  const key = `${kind}?${encoded}`
  const [revision, setRevision] = useState(0)
  const [state, setState] = useState<State<T>>(() => {
    const saved = cache.get(key)
    return saved
      ? {
          ...empty<T>(key),
          result: saved.result as PageResult<T>,
          loading: false,
        }
      : empty<T>(key)
  })
  const current = state.key === key ? state : empty<T>(key)
  const stateRef = useRef(current)
  stateRef.current = current
  const controllerRef = useRef<AbortController | null>(null),
    moreBusy = useRef<AbortController | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    controllerRef.current = controller
    moreBusy.current = null
    const saved = cache.get(key)
    if (saved) {
      setState({
        ...empty<T>(key),
        result: saved.result as PageResult<T>,
        loading: false,
      })
    } else {
      setState(empty<T>(key))
      request<T>(`/api/reader/${kind}?${encoded}`, controller.signal)
        .then((result) => {
          if (controller.signal.aborted) return
          remember(key, result)
          setState({ ...empty<T>(key), result, loading: false })
        })
        .catch((e) => {
          if (!controller.signal.aborted)
            setState({
              ...empty<T>(key),
              loading: false,
              error: e.message || '加载失败',
            })
        })
    }
    // Check for new content without changing the current reading window or scroll.
    let checking = false
    const check = async () => {
      const latest = stateRef.current
      if (
        checking ||
        document.visibilityState !== 'visible' ||
        latest.loading ||
        !latest.result ||
        latest.newContent
      )
        return
      checking = true
      try {
        const fresh = await request<T>(
          `/api/reader/${kind}?${encoded}`,
          controller.signal,
        )
        if (controller.signal.aborted) return
        const known = new Set(stateRef.current.result?.data.map((r) => r.id))
        if (
          fresh.total > (stateRef.current.result?.total || 0) ||
          fresh.data.some((r) => !known.has(r.id))
        )
          setState((previous) =>
            previous.key === key ? { ...previous, newContent: true } : previous,
          )
      } catch {
        /* A failed background check must not replace a readable list with an error. */
      } finally {
        checking = false
      }
    }
    const timer = setInterval(check, 60_000)
    if (saved) void check()
    return () => {
      controller.abort()
      clearInterval(timer)
    }
  }, [key, kind, encoded, revision])
  const loadMore = useCallback(async () => {
    const controller = controllerRef.current,
      latest = stateRef.current,
      result = latest.result
    if (
      !controller ||
      controller.signal.aborted ||
      moreBusy.current ||
      latest.key !== key ||
      latest.loading ||
      !result?.hasMore ||
      !result.nextCursor
    )
      return
    moreBusy.current = controller
    setState((previous) => ({ ...previous, loadingMore: true, moreError: '' }))
    try {
      const next = await request<T>(
        `/api/reader/${kind}?${encoded}&cursor=${encodeURIComponent(result.nextCursor)}`,
        controller.signal,
      )
      if (controller.signal.aborted) return
      if (next.hasMore && next.nextCursor === result.nextCursor)
        throw new Error('加载位置未前进，请刷新列表')
      setState((previous) => {
        if (previous.key !== key || !previous.result) return previous
        const merged = {
          ...next,
          data: mergeReaderRows(previous.result.data, next.data),
        }
        remember(key, merged)
        return {
          ...previous,
          result: merged,
          loadingMore: false,
          moreError: '',
        }
      })
    } catch (e) {
      if (!controller.signal.aborted)
        setState((previous) =>
          previous.key === key
            ? {
                ...previous,
                loadingMore: false,
                moreError: e instanceof Error ? e.message : '加载失败',
              }
            : previous,
        )
    } finally {
      if (moreBusy.current === controller) moreBusy.current = null
    }
  }, [key, kind, encoded])
  const refresh = useCallback(() => {
    cache.delete(key)
    controllerRef.current?.abort()
    setState(empty<T>(key))
    setRevision((v) => v + 1)
  }, [key])
  return { ...current, cacheKey: key, loadMore, refresh }
}
