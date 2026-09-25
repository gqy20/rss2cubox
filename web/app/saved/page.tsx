'use client'
import { useEffect, useState } from 'react'
import type { Row } from '../types'
import type { Policy } from '../../lib/journal-types'
import { getBookmarks } from '../journal/Actions'
import { SearchTrigger } from '../journal/SearchPalette'
import { PageHeading, Empty, ArticleRows, PolicyRows } from '../journal/Shared'
import { useWindowReadingPosition } from '../../hooks/useReadingPosition'
export default function SavedPage() {
  const [rows, setRows] = useState<Row[]>([]),
    [policies, setPolicies] = useState<Policy[]>([]),
    [loading, setLoading] = useState(true),
    [missing, setMissing] = useState(0),
    [failed, setFailed] = useState(false),
    [retry, setRetry] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      const signal = controller.signal
      setLoading(true)
      const article: string[] = [],
        policy: string[] = []
      for (const key of getBookmarks()) {
        const index = key.indexOf(':'),
          kind = key.slice(0, index),
          id = key.slice(index + 1)
        if (kind === 'article') article.push(id)
        else if (kind === 'policy') policy.push(id)
      }
      const wanted = article.length + policy.length
      try {
        const response = await fetch('/api/reader/saved', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ article, policy }),
          signal,
        })
        if (!response.ok) throw new Error()
        const { data } = (await response.json()) as {
          data: { articles: Row[]; policies: Policy[] }
        }
        if (signal.aborted) return
        setRows(
          [...data.articles].sort(
            (a, b) =>
              Date.parse(b.time) - Date.parse(a.time) ||
              (a.id < b.id ? 1 : a.id > b.id ? -1 : 0),
          ),
        )
        setPolicies(
          [...data.policies].sort(
            (a, b) =>
              (Date.parse(b.published_at || '') || 0) -
                (Date.parse(a.published_at || '') || 0) ||
              (a.id < b.id ? 1 : a.id > b.id ? -1 : 0),
          ),
        )
        setMissing(wanted - data.articles.length - data.policies.length)
        setFailed(false)
        setLoading(false)
      } catch {
        if (signal.aborted) return
        setFailed(true)
        setLoading(false)
      }
    }
    void load()
    window.addEventListener('bookmarks-change', load)
    window.addEventListener('storage', load)
    return () => {
      controller.abort()
      window.removeEventListener('bookmarks-change', load)
      window.removeEventListener('storage', load)
    }
  }, [retry])
  useWindowReadingPosition('saved', !loading)
  return (
    <>
      <PageHeading title="我的收藏" />
      {(failed || missing > 0) && (
        <div className="data-notice" role="status">
          {failed
            ? '收藏暂时无法加载。'
            : `${missing} 条收藏暂时无法加载。`}
          <button
            className="soft-button"
            onClick={() => setRetry((v) => v + 1)}
          >
            重试
          </button>
        </div>
      )}
      <section className="surface">
        <div className="saved-bar">
          <SearchTrigger />
        </div>
        {loading ? (
          <div className="loading-skeleton" />
        ) : rows.length || policies.length ? (
          <>
            {rows.length > 0 && (
              <ArticleRows
                rows={rows}
                context={{ from: '/saved', filters: { saved: '1' } }}
              />
            )}
            {policies.length > 0 && (
              <PolicyRows
                rows={policies}
                context={{ from: '/saved' }}
                withBookmark
              />
            )}
          </>
        ) : (
          <Empty
            title="还没有收藏"
            description="在文章或政策详情中点击书签，即可留在这里。"
          />
        )}
      </section>
      <p className="snapshot-note">收藏保存在当前浏览器，不跨设备同步。</p>
    </>
  )
}
