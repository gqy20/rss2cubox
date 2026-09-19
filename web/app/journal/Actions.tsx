'use client'
import { useEffect, useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { Bookmark, Download, RefreshCw, Check } from 'lucide-react'
const KEY = 'rss-brief-bookmarks'
export function getBookmarks(): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(KEY) || '[]')
    return Array.isArray(value)
      ? value.filter((s): s is string => typeof s === 'string')
      : []
  } catch {
    return []
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
    [saved, setSaved] = useState(false),
    [error, setError] = useState(false)
  useEffect(() => {
    const update = () => setSaved(getBookmarks().includes(key))
    update()
    window.addEventListener('bookmarks-change', update)
    window.addEventListener('storage', update)
    return () => {
      window.removeEventListener('bookmarks-change', update)
      window.removeEventListener('storage', update)
    }
  }, [key])
  return (
    <button
      className={`icon-button bookmark-button ${saved ? 'is-saved' : ''}`}
      title={
        error ? '浏览器无法保存收藏' : saved ? '取消收藏' : '收藏到此浏览器'
      }
      aria-label={saved ? '取消收藏' : '收藏'}
      aria-pressed={saved}
      onClick={() => {
        try {
          const all = getBookmarks()
          localStorage.setItem(
            KEY,
            JSON.stringify(
              saved ? all.filter((s) => s !== key) : [...all, key],
            ),
          )
          window.dispatchEvent(new Event('bookmarks-change'))
          setError(false)
        } catch {
          setError(true)
        }
      }}
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
      className="soft-button"
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
        URL.revokeObjectURL(url)
        setDone(true)
      }}
    >
      {done ? <Check size={15} /> : <Download size={15} />}
      {done ? '已导出' : '导出 JSON'}
    </button>
  )
}
export function RefreshButton() {
  const router = useRouter(),
    [pending, start] = useTransition()
  return (
    <button
      className="soft-button"
      disabled={pending}
      onClick={() => start(() => router.refresh())}
    >
      <RefreshCw size={15} className={pending ? 'spin' : ''} />
      {pending ? '更新中…' : '刷新数据'}
    </button>
  )
}
