'use client'

import { useState, useRef, useEffect, useCallback } from 'react'

export function useRowInteraction() {
  const [hoveredRowKey, setHoveredRowKey] = useState<string | null>(null)
  const hoverCloseTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})

  useEffect(() => {
    return () => {
      Object.values(hoverCloseTimers.current).forEach((timer) => clearTimeout(timer))
    }
  }, [])

  const openRowHover = useCallback((key: string) => {
    const timer = hoverCloseTimers.current[key]
    if (timer) { clearTimeout(timer); delete hoverCloseTimers.current[key] }
    setHoveredRowKey(key)
  }, [])

  const closeRowHover = useCallback((key: string) => {
    hoverCloseTimers.current[key] = setTimeout(() => {
      setHoveredRowKey((prev) => (prev === key ? null : prev))
      delete hoverCloseTimers.current[key]
    }, 140)
  }, [])

  const toggleRowOpen = useCallback((key: string) => {
    const timer = hoverCloseTimers.current[key]
    if (timer) { clearTimeout(timer); delete hoverCloseTimers.current[key] }
    setHoveredRowKey((prev) => (prev === key ? null : key))
  }, [])

  return {
    hoveredRowKey,
    onHoverEnter: openRowHover,
    onHoverLeave: closeRowHover,
    onToggleOpen: toggleRowOpen,
  }
}
