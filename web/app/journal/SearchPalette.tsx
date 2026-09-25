'use client'
import { useEffect, useState } from 'react'
import { usePathname } from 'next/navigation'
import { Search } from 'lucide-react'
import SearchBar from './SearchBar'

export const OPEN_SEARCH_EVENT = 'search-palette:open'

/** Sits in a page's first row; the palette itself lives in the shell. */
export function SearchTrigger({ className = '' }: { className?: string }) {
  return (
    <button
      type="button"
      className={`icon-button search-trigger ${className}`}
      aria-label="搜索文章或政策"
      title="搜索文章或政策（⌘K / /）"
      onClick={() => window.dispatchEvent(new Event(OPEN_SEARCH_EVENT))}
    >
      <Search size={17} />
    </button>
  )
}

/** Command-palette search: one overlay for every page, opened via the row
 *  triggers, ⌘K / Ctrl+K, or "/". Reuses SearchBar for scope + IME handling. */
export default function SearchPalette() {
  const [open, setOpen] = useState(false)
  const pathname = usePathname()
  useEffect(() => setOpen(false), [pathname])
  useEffect(() => {
    const openPalette = () => setOpen(true)
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing) return
      const editing = (e.target as HTMLElement)?.matches(
        'input,textarea,select,[contenteditable="true"]',
      )
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((v) => !v)
      } else if (e.key === '/' && !editing) {
        e.preventDefault()
        setOpen(true)
      } else if (e.key === 'Escape') {
        setOpen(false)
      }
    }
    window.addEventListener(OPEN_SEARCH_EVENT, openPalette)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener(OPEN_SEARCH_EVENT, openPalette)
      window.removeEventListener('keydown', onKey)
    }
  }, [])
  if (!open) return null
  return (
    <div
      className="search-palette-backdrop"
      onClick={() => setOpen(false)}
    >
      <div
        className="search-palette"
        role="dialog"
        aria-modal="true"
        aria-label="搜索"
        onClick={(e) => e.stopPropagation()}
      >
        <SearchBar autoFocus onSubmitted={() => setOpen(false)} />
        <p className="search-palette-hint">Enter 搜索 · Esc 关闭</p>
      </div>
    </div>
  )
}
