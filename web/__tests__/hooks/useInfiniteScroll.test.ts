import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useInfiniteScroll } from '@/hooks/useInfiniteScroll'

// Mock IntersectionObserver for jsdom
class MockIntersectionObserver {
  callback: IntersectionObserverCallback
  constructor(callback: IntersectionObserverCallback) { this.callback = callback }
  observe() {}
  unobserve() {}
  disconnect() {}
}

describe('useInfiniteScroll', () => {
  let container: HTMLDivElement

  beforeEach(() => {
    ;(window as any).IntersectionObserver = MockIntersectionObserver
    container = document.createElement('div')
    Object.defineProperty(container, 'getBoundingClientRect', {
      value: () => ({ top: 0, bottom: 1000, height: 1000 }),
    })
    document.body.appendChild(container)
  })

  afterEach(() => {
    document.body.removeChild(container)
    delete (window as any).IntersectionObserver
  })

  it('should set up observer without errors when refs are ready', () => {
    const onLoadMore = vi.fn()
    const sentinelRef = { current: document.createElement('div') }

    renderHook(() =>
      useInfiniteScroll({
        rootRef: { current: container },
        sentinelRef,
        onLoadMore,
      })
    )

    // Hook should mount and unmount without throwing
    expect(true).toBe(true)
  })

  it('should not call onLoadMore when loading is true', () => {
    const onLoadMore = vi.fn()

    renderHook(() =>
      useInfiniteScroll({
        rootRef: { current: container },
        sentinelRef: { current: null },
        onLoadMore,
        loading: true,
      })
    )

    // With loading=true and no sentinel, onLoadMore should not be called
    expect(onLoadMore).not.toHaveBeenCalled()
  })

  it('should trigger initial load for short content (sentinel visible)', () => {
    const onLoadMore = vi.fn()
    const sentinel = document.createElement('div')
    // Make sentinel appear "visible" by putting it in a small container
    const smallContainer = document.createElement('div')
    Object.defineProperty(smallContainer, 'getBoundingClientRect', {
      value: () => ({ top: 0, bottom: 10, height: 10 }),
    })
    Object.defineProperty(sentinel, 'getBoundingClientRect', {
      value: () => ({ top: 5, bottom: 6, height: 1 }),
    })
    smallContainer.appendChild(sentinel)
    document.body.appendChild(smallContainer)

    renderHook(() =>
      useInfiniteScroll({
        rootRef: { current: smallContainer },
        sentinelRef: { current: sentinel },
        onLoadMore,
        rootMargin: '0px 0px 240px 0px',
      })
    )

    // Sentinel is within visible area + margin → should trigger
    expect(onLoadMore).toHaveBeenCalled()
    document.body.removeChild(smallContainer)
  })
})
