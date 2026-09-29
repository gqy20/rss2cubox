import type { Cluster } from './journal-types'
import { plainText } from './journal-utils'
export function excludedTopic(topic: Cluster) {
  return (
    ['invalid', 'archived'].includes(topic.status) || topic.article_count === 0
  )
}
// 多源共振（借鉴 AIHOT 的"独立来源数 = 热度"）：同一事件被 ≥3 个独立
// 信源报道即是热点，排序优先于单纯新鲜的簇。
export const RESONANCE_MIN = 3
export function isResonant(topic: Cluster) {
  return topic.source_count >= RESONANCE_MIN
}
export function orderedTopics(topics: Cluster[]) {
  return [...topics].sort(
    (a, b) =>
      Number(excludedTopic(a)) - Number(excludedTopic(b)) ||
      Number(isResonant(b)) - Number(isResonant(a)) ||
      (isResonant(a) && isResonant(b) ? b.source_count - a.source_count : 0) ||
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
