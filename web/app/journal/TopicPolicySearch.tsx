'use client'
import { useState } from 'react'
import Link from 'next/link'
import { Search } from 'lucide-react'
import { withOrigin } from '../../lib/reading-context'
export default function TopicPolicySearch({
  terms,
  from,
}: {
  terms: string[]
  from: string
}) {
  const [term, setTerm] = useState(terms[0] || '')
  return terms.length ? (
    <div className="topic-policy-search">
      <label>
        查政策
        <select
          aria-label="政策检索关键词"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
        >
          {terms.map((word) => (
            <option key={word}>{word}</option>
          ))}
        </select>
      </label>
      <Link
        className="icon-button"
        aria-label={`用“${term}”查找政策`}
        title={`用“${term}”查找政策`}
        href={withOrigin(`/policies?search=${encodeURIComponent(term)}`, from)}
      >
        <Search size={15} />
      </Link>
    </div>
  ) : (
    <Link className="text-link" href={withOrigin('/policies', from)}>
      进入政策库
    </Link>
  )
}
