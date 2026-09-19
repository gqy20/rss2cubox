'use client'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Search, X, ArrowRight } from 'lucide-react'
import {
  readerUrl,
  scopeForPath,
  type SearchScope,
} from '../../lib/reader-search'

export default function SearchBar() {
  const pathname = usePathname(),
    params = useSearchParams(),
    router = useRouter()
  const inReader = pathname === '/signals' || pathname === '/policies'
  const committed = inReader ? params.get('search') || '' : ''
  const [draft, setDraft] = useState(committed),
    [scope, setScope] = useState<SearchScope>(scopeForPath(pathname))
  const [composing, setComposing] = useState(false)
  const input = useRef<HTMLInputElement>(null),
    ime = useRef(false),
    timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const queryString = params.toString()
  const cancelTimer = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
  }, [])
  useEffect(() => {
    cancelTimer()
    setDraft(committed)
    setScope(scopeForPath(pathname))
  }, [pathname, committed, cancelTimer])
  const commit = useCallback(
    (value: string, target = scope, explicit = false) => {
      cancelTimer()
      const keyword = value.trim().slice(0, 300)
      if (!inReader && !keyword) return
      const sameScope = pathname === `/${target}`
      const url = readerUrl(
        target,
        new URLSearchParams(sameScope ? queryString : ''),
        { search: keyword },
      )
      if (url === `${pathname}${queryString ? `?${queryString}` : ''}`) return
      if (sameScope) {
        // Native history updates URL subscribers without remounting the reader or losing focus.
        window.history[explicit ? 'pushState' : 'replaceState'](null, '', url)
      } else router.push(url)
    },
    [cancelTimer, scope, inReader, pathname, queryString, router],
  )
  useEffect(() => {
    cancelTimer()
    if (!inReader || composing || draft.trim() === committed) return
    timer.current = setTimeout(() => commit(draft), 350)
    return cancelTimer
  }, [draft, committed, composing, inReader, commit, cancelTimer])
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.isComposing) return
      const editing = (e.target as HTMLElement)?.matches(
        'input,textarea,select,[contenteditable="true"]',
      )
      if (
        ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') ||
        (e.key === '/' && !editing)
      ) {
        e.preventDefault()
        input.current?.focus()
        input.current?.select()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])
  return (
    <form
      className="global-search"
      role="search"
      onSubmit={(e) => {
        e.preventDefault()
        if (ime.current) return
        commit(draft, scope, true)
      }}
    >
      <Search size={17} aria-hidden="true" />
      <select
        className="search-scope"
        aria-label="搜索范围"
        value={scope}
        onChange={(e) => {
          const target = e.target.value as SearchScope
          cancelTimer()
          setScope(target)
          if (inReader) commit(draft, target, true)
        }}
      >
        <option value="signals">文章</option>
        <option value="policies">政策</option>
      </select>
      <input
        ref={input}
        type="search"
        aria-label={scope === 'signals' ? '搜索文章' : '搜索政策'}
        placeholder={
          scope === 'signals'
            ? '搜索标题、摘要、正文…'
            : '搜索政策、机构、条款…'
        }
        maxLength={300}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onCompositionStart={() => {
          ime.current = true
          setComposing(true)
          cancelTimer()
        }}
        onCompositionEnd={(e) => {
          ime.current = false
          setComposing(false)
          setDraft(e.currentTarget.value)
        }}
        onKeyDown={(e) => {
          if (
            e.key === 'Enter' &&
            (e.nativeEvent.isComposing || ime.current || e.keyCode === 229)
          ) {
            e.preventDefault()
            return
          }
          if (e.key === 'Escape' && !ime.current) {
            e.preventDefault()
            cancelTimer()
            setDraft(committed)
            input.current?.blur()
          }
        }}
      />
      {draft && (
        <button
          type="button"
          className="search-action"
          aria-label="清空搜索"
          title="清空搜索"
          onClick={() => {
            cancelTimer()
            setDraft('')
            if (inReader) commit('')
            input.current?.focus()
          }}
        >
          <X size={15} />
        </button>
      )}
      {draft ? (
        <button
          type="submit"
          className="search-action"
          aria-label="立即搜索"
          title="立即搜索"
          disabled={composing}
        >
          <ArrowRight size={16} />
        </button>
      ) : (
        <kbd aria-hidden="true">⌘ K</kbd>
      )}
    </form>
  )
}
