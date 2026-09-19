'use client'
import * as Popover from '@radix-ui/react-popover'
import { useEffect, useId, useRef, useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { Search, ChevronDown, Check, Layers3, LoaderCircle } from 'lucide-react'
import type { Cluster } from '../../lib/journal-types'
import { withOrigin } from '../../lib/reading-context'
import { clearMemory } from '../../lib/reading-memory'
import { clusterStatus } from '../../lib/journal-utils'
import { excludedTopic, matchingTopics } from '../../lib/topic-utils'
export default function TopicSelector({
  topics,
  selectedId,
  returnTo,
}: {
  topics: Cluster[]
  selectedId?: number
  returnTo?: string | null
}) {
  const router = useRouter(),
    [open, setOpen] = useState(false),
    [query, setQuery] = useState(''),
    [includeExcluded, setIncludeExcluded] = useState(false),
    [active, setActive] = useState(0),
    [pending, startTransition] = useTransition()
  const input = useRef<HTMLInputElement>(null),
    list = useRef<HTMLDivElement>(null),
    id = useId()
  const choices = matchingTopics(topics, query, includeExcluded)
  const activeTopic = choices[Math.min(active, Math.max(choices.length - 1, 0))]
  const selected = topics.find((t) => t.id === selectedId)
  useEffect(() => {
    if (!pending) setOpen(false)
  }, [selectedId, pending])
  useEffect(() => {
    const item = list.current?.querySelector<HTMLElement>(
      '[data-active="true"]',
    )
    item?.scrollIntoView?.({ block: 'nearest' })
  }, [active, query])
  const choose = (topic: Cluster) => {
    setOpen(false)
    if (topic.id !== selectedId) {
      clearMemory(`scroll:topic:${topic.id}`)
      startTransition(() =>
        router.push(withOrigin(`/topics?id=${topic.id}`, returnTo), {
          scroll: false,
        }),
      )
    }
  }
  return (
    <Popover.Root
      open={open}
      onOpenChange={(value) => {
        setOpen(value)
        if (value) {
          setQuery('')
          const showExcluded = Boolean(selected && excludedTopic(selected))
          setIncludeExcluded(showExcluded)
          setActive(
            Math.max(
              0,
              matchingTopics(topics, '', showExcluded).findIndex(
                (topic) => topic.id === selectedId,
              ),
            ),
          )
        }
      }}
    >
      <Popover.Trigger asChild>
        <button
          className="topic-select-trigger"
          aria-label={
            selected ? `切换专题，当前：${selected.label}` : '选择专题'
          }
          disabled={pending}
        >
          <Layers3 size={16} />
          <span>{pending ? '切换中…' : '切换专题'}</span>
          <small>{topics.filter((t) => !excludedTopic(t)).length}</small>
          {pending ? (
            <LoaderCircle className="spin" size={15} />
          ) : (
            <ChevronDown size={15} />
          )}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          className="topic-select-popover"
          align="end"
          sideOffset={9}
          collisionPadding={14}
          aria-label="选择专题"
          onOpenAutoFocus={(e) => {
            e.preventDefault()
            input.current?.focus()
          }}
        >
          <div className="topic-select-search">
            <Search size={16} />
            <input
              ref={input}
              value={query}
              placeholder="搜索专题、实体或关键词…"
              role="combobox"
              aria-label="查找专题"
              aria-expanded={open}
              aria-controls={id}
              aria-autocomplete="list"
              aria-activedescendant={
                activeTopic ? `${id}-${activeTopic.id}` : undefined
              }
              onChange={(e) => {
                setQuery(e.target.value)
                setActive(0)
              }}
              onKeyDown={(e) => {
                if (e.nativeEvent.isComposing || e.keyCode === 229) return
                if (e.key === 'ArrowDown') {
                  e.preventDefault()
                  setActive((i) => Math.min(i + 1, choices.length - 1))
                }
                if (e.key === 'ArrowUp') {
                  e.preventDefault()
                  setActive((i) => Math.max(i - 1, 0))
                }
                if (e.key === 'Enter' && activeTopic) {
                  e.preventDefault()
                  choose(activeTopic)
                }
              }}
            />
          </div>
          <div
            className="topic-select-options"
            ref={list}
            role="listbox"
            id={id}
            aria-label="专题列表"
          >
            {choices.map((topic, index) => (
              <button
                type="button"
                role="option"
                id={`${id}-${topic.id}`}
                aria-selected={topic.id === selectedId}
                tabIndex={-1}
                data-active={topic.id === activeTopic?.id}
                className="topic-select-option"
                key={topic.id}
                onMouseEnter={() => setActive(index)}
                onClick={() => choose(topic)}
              >
                <span>
                  <strong>{topic.label}</strong>
                  <small>
                    {topic.article_count} 篇文章 · {topic.source_count} 个来源
                    <span>{clusterStatus[topic.status] || '待确认'}</span>
                  </small>
                </span>
                {topic.id === selectedId && <Check size={16} />}
              </button>
            ))}
            {choices.length === 0 && (
              <p className="topic-select-empty" role="status">
                没有匹配的专题
              </p>
            )}
          </div>
          <div className="topic-select-footer">
            <label>
              <input
                type="checkbox"
                checked={includeExcluded}
                onChange={(e) => {
                  setIncludeExcluded(e.target.checked)
                  setActive(0)
                }}
              />
              包含已排除专题
            </label>
            <span>{choices.length} 个结果</span>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
