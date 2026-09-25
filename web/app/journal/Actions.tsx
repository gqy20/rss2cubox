'use client'
import { useEffect, useState, useSyncExternalStore, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { Bookmark, Download, RefreshCw, Check } from 'lucide-react'
const KEY = 'rss-brief-bookmarks'
const EMPTY: string[] = []
// One cached parse + one pair of window listeners, shared by every
// BookmarkButton on the page instead of one per row.
let cached: string[] | null = null
export function getBookmarks(): string[] {
  if (cached) return cached
  try {
    const value: unknown = JSON.parse(localStorage.getItem(KEY) || '[]')
    cached = Array.isArray(value)
      ? value.filter((s): s is string => typeof s === 'string')
      : EMPTY
  } catch {
    cached = EMPTY
  }
  return cached
}
const listeners = new Set<() => void>()
const notify = () => listeners.forEach((listener) => listener())
const onExternalChange = () => {
  cached = null
  notify()
}
let listening = 0
function subscribeBookmarks(onStoreChange: () => void) {
  if (listening++ === 0) {
    window.addEventListener('bookmarks-change', notify)
    window.addEventListener('storage', onExternalChange)
  }
  listeners.add(onStoreChange)
  return () => {
    listeners.delete(onStoreChange)
    if (--listening === 0) {
      window.removeEventListener('bookmarks-change', notify)
      window.removeEventListener('storage', onExternalChange)
    }
  }
}
function toggleBookmark(key: string): boolean {
  try {
    const all = getBookmarks(),
      next = all.includes(key) ? all.filter((s) => s !== key) : [...all, key]
    localStorage.setItem(KEY, JSON.stringify(next))
    cached = next
    window.dispatchEvent(new Event('bookmarks-change'))
    return true
  } catch {
    return false
  }
}
export function BookmarkButton({
  id,
  kind = 'article',
}: {
  id: string
  kind?: 'article' | 'policy'
}) {
  const key = `${kind}:${id}`,
    all = useSyncExternalStore(subscribeBookmarks, getBookmarks, () => EMPTY),
    saved = all.includes(key),
    [error, setError] = useState(false)
  return (
    <button
      className={`icon-button bookmark-button ${saved ? 'is-saved' : ''}`}
      title={
        error ? '浏览器无法保存收藏' : saved ? '取消收藏' : '收藏到此浏览器'
      }
      aria-label={saved ? '取消收藏' : '收藏'}
      aria-pressed={saved}
      onClick={() => setError(!toggleBookmark(key))}
    >
      <Bookmark size={17} fill={saved ? 'currentColor' : 'none'} />
      {error && (
        <span className="sr-only" role="alert">
          收藏失败，浏览器存储不可用
        </span>
      )}
    </button>
  )
}
export function ExportButton({
  data,
  name = 'rss-brief',
}: {
  data: unknown
  name?: string
}) {
  const [done, setDone] = useState(false)
  useEffect(() => {
    if (!done) return
    const timer = setTimeout(() => setDone(false), 1800)
    return () => clearTimeout(timer)
  }, [done])
  return (
    <button
      className="icon-button"
      title={done ? '已导出' : '导出 JSON'}
      aria-label={done ? '已导出' : '导出 JSON'}
      onClick={() => {
        const url = URL.createObjectURL(
          new Blob([JSON.stringify(data, null, 2)], {
            type: 'application/json',
          }),
        )
        const a = document.createElement('a')
        a.href = url
        a.download = `${name}.json`
        a.click()
        // Revoking synchronously can cancel the download before it starts.
        setTimeout(() => URL.revokeObjectURL(url), 1000)
        setDone(true)
      }}
    >
      {done ? <Check size={17} /> : <Download size={17} />}
      <span className="sr-only" role="status">
        {done ? '已导出' : ''}
      </span>
    </button>
  )
}
export function RefreshButton() {
  const router = useRouter(),
    [pending, start] = useTransition()
  return (
    <button
      className="icon-button"
      title={pending ? '更新中' : '刷新数据'}
      aria-label={pending ? '更新中' : '刷新数据'}
      disabled={pending}
      onClick={() => start(() => router.refresh())}
    >
      <RefreshCw size={17} className={pending ? 'spin' : ''} />
    </button>
  )
}
