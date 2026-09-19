'use client'
import Link from 'next/link'
import { useRef, type ReactNode } from 'react'
import { ArrowLeft } from 'lucide-react'
import { safeReturnPath, returnLabel } from '../../lib/reading-context'
import {
  useReadingPosition,
  useWindowReadingPosition,
} from '../../hooks/useReadingPosition'
export function ReturnLink({
  from,
  fallback = '/policies',
  className = 'breadcrumb',
}: {
  from?: string | null
  fallback?: string
  className?: string
}) {
  const destination = safeReturnPath(from) || fallback
  return (
    <Link href={destination} scroll={false} className={className}>
      <ArrowLeft size={14} />
      {returnLabel(destination)}
    </Link>
  )
}
export function ReadingRegion({
  memoryKey,
  className,
  children,
  label,
}: {
  memoryKey: string
  className: string
  children: ReactNode
  label: string
}) {
  const ref = useRef<HTMLElement>(null)
  useReadingPosition(ref, memoryKey)
  return (
    <article ref={ref} className={className} tabIndex={0} aria-label={label}>
      {children}
    </article>
  )
}
export function WindowReadingPosition({
  memoryKey,
  ready = true,
}: {
  memoryKey: string
  ready?: boolean
}) {
  useWindowReadingPosition(memoryKey, ready)
  return null
}
