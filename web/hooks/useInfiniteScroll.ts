'use client'

import { useEffect, useRef, useCallback } from 'react'

export type UseInfiniteScrollOptions = {
  rootRef: React.RefObject<HTMLElement | null>
  sentinelRef: React.RefObject<HTMLDivElement | null>
  onLoadMore: () => void
  loading?: boolean
  rootMargin?: string
  threshold?: number
}

export function useInfiniteScroll({
  rootRef,
  sentinelRef,
  onLoadMore,
  loading = false,
  rootMargin = '0px 0px 240px 0px',
  threshold = 0.01,
}: UseInfiniteScrollOptions) {
  const triggeredRef = useRef(false)

  // Unified scroll detection using IntersectionObserver only.
  // This replaces the previous dual-listener approach (IO + scroll event).
  // The scroll event was originally a fallback for short content where the
  // sentinel starts visible — we handle that with an initial check instead.
  useEffect(() => {
    const root = rootRef.current
    const target = sentinelRef.current
    if (!root || !target || loading) return

    // Initial check: if sentinel is already visible (short content), trigger immediately
    const rootRect = root.getBoundingClientRect()
    const targetRect = target.getBoundingClientRect()
    const isVisible = targetRect.top <= rootRect.bottom + parseInt(rootMargin.split(' ')[3] || '0')

    if (isVisible && !triggeredRef.current) {
      triggeredRef.current = true
      onLoadMore()
      return // Don't set up observer for one-shot initial case; caller will re-invoke
    }

    const observer = new IntersectionObserver(
      (entries) => {
        const first = entries[0]
        if (!first?.isIntersecting) return
        if (loading) return
        triggeredRef.current = true
        onLoadMore()
      },
      { root, rootMargin, threshold },
    )

    observer.observe(target)
    return () => { observer.disconnect(); triggeredRef.current = false }
  }, [rootRef, sentinelRef, onLoadMore, loading, rootMargin, threshold])

  // Reset triggered flag when loading state changes (allows re-trigger after data loads)
  useEffect(() => {
    if (!loading) {
      triggeredRef.current = false
    }
  }, [loading])
}
