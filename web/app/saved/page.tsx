'use client'
import { useEffect, useState } from 'react'
import type { Row } from '../types'
import type { Policy } from '../../lib/journal-types'
import { getBookmarks, BookmarkButton } from '../journal/Actions'
import { PageHeading, Empty, ArticleRows } from '../journal/Shared'
import Link from 'next/link'
import { policyDestination } from '../../lib/reading-context'
import { useWindowReadingPosition } from '../../hooks/useReadingPosition'
export default function SavedPage() {
  const [rows, setRows] = useState<Row[]>([]),
    [policies, setPolicies] = useState<Policy[]>([]),
    [loading, setLoading] = useState(true),
    [missing, setMissing] = useState(0),
    [retry, setRetry] = useState(0)
  useEffect(() => {
    let controller = new AbortController()
    const load = async () => {
      controller.abort()
      controller = new AbortController()
      const signal = controller.signal
      setLoading(true)
      const ids = getBookmarks(),
        articles: Row[] = [],
        docs: Policy[] = []
      let failures = 0
      for (let start = 0; start < ids.length; start += 6) {
        if (signal.aborted) return
        await Promise.all(
          ids.slice(start, start + 6).map(async (key) => {
            const index = key.indexOf(':'),
              kind = key.slice(0, index),
              id = key.slice(index + 1)
            if (!['article', 'policy'].includes(kind)) return
            try {
              const response = await fetch(
                `/api/reader/${kind}?id=${encodeURIComponent(id)}`,
                { signal },
              )
              if (!response.ok) throw new Error()
              const { data } = await response.json()
              if (kind === 'article') articles.push(data)
              else docs.push(data)
            } catch {
              failures++
            }
          }),
        )
      }
      if (!signal.aborted) {
        setRows(
          articles.sort(
            (a, b) =>
              Date.parse(b.time) - Date.parse(a.time) ||
              (a.id < b.id ? 1 : a.id > b.id ? -1 : 0),
          ),
        )
        setPolicies(
          docs.sort(
            (a, b) =>
              (Date.parse(b.published_at || '') || 0) -
                (Date.parse(a.published_at || '') || 0) ||
              (a.id < b.id ? 1 : a.id > b.id ? -1 : 0),
          ),
        )
        setMissing(failures)
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
      {missing > 0 && (
        <div className="data-notice">
          {missing} 条收藏暂时无法加载。
          <button
            className="soft-button"
            onClick={() => setRetry((v) => v + 1)}
          >
            重试
          </button>
        </div>
      )}
      <section className="surface">
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
            {policies.map((p) => (
              <div className="reading-row" key={p.id}>
                <Link
                  className="reading-copy reading-title"
                  href={policyDestination(p.id, { from: '/saved' })}
                >
                  {p.title}
                  <span className="metadata">政策 · {p.region}</span>
                </Link>
                <BookmarkButton id={p.id} kind="policy" />
              </div>
            ))}
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
