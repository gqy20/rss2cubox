'use client'
import * as Popover from '@radix-ui/react-popover'
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, Search } from 'lucide-react'

export type SelectOption = { value: string; label: string }

/** Unified styled select: native <select> dropdowns render with the OS theme
 *  and clash with the design. Same semantics as a select: listbox popover,
 *  arrow-key navigation, Enter to choose, Esc to dismiss, long lists get a
 *  filter box. Pass `name` when a real form submission must carry the value. */
export default function Select({
  value,
  defaultValue,
  options,
  onChange,
  ariaLabel,
  name,
  className,
  filterThreshold = 12,
}: {
  /** Controlled mode; omit and pass defaultValue for uncontrolled (forms). */
  value?: string
  defaultValue?: string
  options: SelectOption[]
  onChange?: (value: string) => void
  ariaLabel: string
  name?: string
  /** Extra trigger class (e.g. the bare in-form variant). */
  className?: string
  filterThreshold?: number
}) {
  const [open, setOpen] = useState(false),
    [query, setQuery] = useState(''),
    [active, setActive] = useState(0),
    [internal, setInternal] = useState(defaultValue ?? '')
  const list = useRef<HTMLDivElement>(null),
    searchInput = useRef<HTMLInputElement>(null),
    id = useId()
  const current = value !== undefined ? value : internal
  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    return keyword
      ? options.filter((o) => o.label.toLowerCase().includes(keyword))
      : options
  }, [options, query])
  const activeOption =
      filtered[Math.min(active, Math.max(filtered.length - 1, 0))],
    selected = options.find((o) => o.value === current),
    filterable = options.length >= filterThreshold
  useEffect(() => {
    list.current
      ?.querySelector<HTMLElement>('[data-active="true"]')
      ?.scrollIntoView?.({ block: 'nearest' })
  }, [active, query])
  const choose = (next: string) => {
    setOpen(false)
    if (next !== current) {
      if (value === undefined) setInternal(next)
      onChange?.(next)
    }
  }
  const onListKeyDown = (e: React.KeyboardEvent) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => Math.min(i + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Home') {
      e.preventDefault()
      setActive(0)
    } else if (e.key === 'End') {
      e.preventDefault()
      setActive(filtered.length - 1)
    } else if (e.key === 'Enter' && activeOption) {
      e.preventDefault()
      choose(activeOption.value)
    }
  }
  return (
    <>
      {name && <input type="hidden" name={name} value={current} />}
      <Popover.Root
        open={open}
        onOpenChange={(next) => {
          setOpen(next)
          if (next) {
            setQuery('')
            setActive(
              Math.max(
                0,
                options.findIndex((o) => o.value === current),
              ),
            )
          }
        }}
      >
        <Popover.Trigger asChild>
          <button
            type="button"
            className={`select-trigger${className ? ` ${className}` : ''}`}
            aria-label={ariaLabel}
          >
            <span className="select-trigger-label">
              {selected?.label ?? ariaLabel}
            </span>
            <ChevronDown size={14} aria-hidden="true" />
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            className="select-popover"
            align="start"
            sideOffset={6}
            collisionPadding={12}
            onOpenAutoFocus={(e) => {
              e.preventDefault()
              if (filterable) searchInput.current?.focus()
              else list.current?.focus()
            }}
          >
            {filterable && (
              <div className="select-search">
                <Search size={13} aria-hidden="true" />
                <input
                  ref={searchInput}
                  value={query}
                  role="combobox"
                  aria-label={`筛选${ariaLabel}`}
                  aria-expanded={open}
                  aria-controls={id}
                  aria-autocomplete="list"
                  aria-activedescendant={
                    activeOption ? `${id}-${activeOption.value}` : undefined
                  }
                  placeholder="输入以筛选…"
                  onChange={(e) => {
                    setQuery(e.target.value)
                    setActive(0)
                  }}
                  onKeyDown={onListKeyDown}
                />
              </div>
            )}
            <div
              className="select-options"
              role="listbox"
              id={id}
              aria-label={ariaLabel}
              tabIndex={-1}
              ref={list}
              onKeyDown={onListKeyDown}
            >
              {filtered.map((option, index) => (
                <button
                  type="button"
                  role="option"
                  id={`${id}-${option.value}`}
                  aria-selected={option.value === current}
                  data-active={index === active}
                  tabIndex={-1}
                  className="select-option"
                  key={option.value || '__empty'}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => choose(option.value)}
                >
                  <span>{option.label}</span>
                  {option.value === current && <Check size={14} />}
                </button>
              ))}
              {filtered.length === 0 && (
                <p className="select-empty" role="status">
                  没有匹配项
                </p>
              )}
            </div>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </>
  )
}
