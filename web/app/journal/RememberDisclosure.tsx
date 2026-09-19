'use client'
import { useLayoutEffect, useState, type ReactNode } from 'react'
import { readMemory, writeMemory } from '../../lib/reading-memory'
export default function RememberDisclosure({
  memoryKey,
  summary,
  children,
}: {
  memoryKey: string
  summary: string
  children: ReactNode
}) {
  const [open, setOpen] = useState(false),
    [ready, setReady] = useState(false)
  useLayoutEffect(() => {
    setOpen(readMemory(memoryKey, false))
    setReady(true)
  }, [memoryKey])
  return (
    <details
      className="disclosure"
      open={open}
      onToggle={(e) => {
        if (!ready) return
        const next = e.currentTarget.open
        setOpen(next)
        writeMemory(memoryKey, next)
      }}
    >
      <summary>{summary}</summary>
      {children}
    </details>
  )
}
