'use client'
import { useLayoutEffect, type RefObject } from 'react'
import { readMemory, writeMemory } from '../lib/reading-memory'
// Scroll fires at display refresh rate; storage writes are rAF-throttled so a
// long read costs at most one JSON.stringify + setItem per frame, not per event.
export function useReadingPosition(
  ref: RefObject<HTMLElement | null>,
  key: string,
  ready = true,
) {
  useLayoutEffect(() => {
    const element = ref.current
    if (!element || !ready) return
    const memoryKey = `scroll:${key}`,
      target = readMemory<number>(memoryKey, 0)
    let restoring = true,
      saveFrame = 0
    const apply = () => {
      if (restoring && element.clientHeight)
        element.scrollTop = Math.max(0, target)
    }
    apply()
    const frame = requestAnimationFrame(() => {
      apply()
      restoring = false
    })
    const save = () => {
      if (restoring || !element.clientHeight || saveFrame) return
      saveFrame = requestAnimationFrame(() => {
        saveFrame = 0
        writeMemory(memoryKey, element.scrollTop)
      })
    }
    const interact = () => {
      restoring = false
    }
    element.addEventListener('scroll', save, { passive: true })
    element.addEventListener('wheel', interact, { passive: true })
    element.addEventListener('touchstart', interact, { passive: true })
    element.addEventListener('keydown', interact)
    return () => {
      cancelAnimationFrame(frame)
      cancelAnimationFrame(saveFrame)
      if (!restoring && element.clientHeight)
        writeMemory(memoryKey, element.scrollTop)
      element.removeEventListener('scroll', save)
      element.removeEventListener('wheel', interact)
      element.removeEventListener('touchstart', interact)
      element.removeEventListener('keydown', interact)
    }
  }, [ref, key, ready])
}
export function useWindowReadingPosition(key: string, ready = true) {
  useLayoutEffect(() => {
    if (!ready) return
    const memoryKey = `window:${key}`,
      route = location.pathname,
      target = readMemory<number>(memoryKey, 0)
    let restoring = true,
      saveFrame = 0
    const frame = requestAnimationFrame(() => {
      window.scrollTo({ top: target })
      restoring = false
    })
    const save = () => {
      if (restoring || location.pathname !== route || saveFrame) return
      saveFrame = requestAnimationFrame(() => {
        saveFrame = 0
        writeMemory(memoryKey, window.scrollY)
      })
    }
    window.addEventListener('scroll', save, { passive: true })
    return () => {
      cancelAnimationFrame(frame)
      cancelAnimationFrame(saveFrame)
      if (!restoring && location.pathname === route)
        writeMemory(memoryKey, window.scrollY)
      window.removeEventListener('scroll', save)
    }
  }, [key, ready])
}
