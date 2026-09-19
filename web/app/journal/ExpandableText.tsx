'use client'
import { useId, useLayoutEffect, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { plainText } from '../../lib/journal-utils'
import { readMemory, writeMemory } from '../../lib/reading-memory'
export default function ExpandableText({
  text,
  limit = 180,
  memoryKey,
}: {
  text: string
  limit?: number
  memoryKey?: string
}) {
  const [expanded, setExpanded] = useState(false),
    id = useId(),
    content = plainText(text),
    long = content.length > limit
  useLayoutEffect(() => {
    if (memoryKey) setExpanded(readMemory(memoryKey, false))
  }, [memoryKey])
  return (
    <div className="expandable-text">
      <p id={id}>
        {long && !expanded ? `${content.slice(0, limit)}…` : content}
      </p>
      {long && (
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={id}
          onClick={() => {
            setExpanded(!expanded)
            if (memoryKey) writeMemory(memoryKey, !expanded)
          }}
        >
          {expanded ? '收起摘要' : '展开摘要'}
          {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>
      )}
    </div>
  )
}
