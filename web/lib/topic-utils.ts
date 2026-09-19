import type { Cluster } from './journal-types'
import { plainText } from './journal-utils'
export function excludedTopic(topic: Cluster) {
  return (
    ['invalid', 'archived'].includes(topic.status) || topic.article_count === 0
  )
}
export function orderedTopics(topics: Cluster[]) {
  return [...topics].sort(
    (a, b) =>
      Number(excludedTopic(a)) - Number(excludedTopic(b)) ||
      (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0) ||
      b.source_count - a.source_count ||
      b.article_count - a.article_count ||
      b.id - a.id,
  )
}
export function matchingTopics(
  topics: Cluster[],
  query: string,
  includeExcluded = false,
) {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  return orderedTopics(topics).filter(
    (topic) =>
      (includeExcluded || !excludedTopic(topic)) &&
      words.every((word) =>
        `${topic.label} ${(topic.entities || []).join(' ')} ${(topic.watch_keywords || []).join(' ')}`
          .toLowerCase()
          .includes(word),
      ),
  )
}
export function topicPolicyTerms(topic: Cluster) {
  return [
    ...new Set(
      [...(topic.entities || []), ...(topic.watch_keywords || [])]
        .map((s) => s.trim())
        .filter((s) => s.length >= 2 && s.length <= 60),
    ),
  ].slice(0, 6)
}
export function articleTeaser(
  title: string,
  summary?: string | null,
  limit = 110,
) {
  const text = plainText(summary)
  if (!text || text.toLowerCase() === plainText(title).toLowerCase())
    return null
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}
