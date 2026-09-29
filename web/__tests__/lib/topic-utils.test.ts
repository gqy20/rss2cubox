import { describe, it, expect } from 'vitest'
import {
  articleTeaser,
  excludedTopic,
  orderedTopics,
  isResonant,
  matchingTopics,
  topicPolicyTerms,
} from '../../lib/topic-utils'
import type { Cluster } from '../../lib/journal-types'
const topic = (id: number, extra: Partial<Cluster> = {}): Cluster => ({
  id,
  label: `Topic ${id}`,
  status: 'warming',
  summary: null,
  article_count: 12,
  source_count: 4,
  entities: [],
  watch_keywords: [],
  updated_at: '2026-09-18T00:00:00Z',
  ...extra,
})
describe('topic reading defaults', () => {
  it('never promotes a newly updated noise cluster over valid topics', () => {
    const list = [
      topic(1, { status: 'invalid', updated_at: '2026-09-19T00:00:00Z' }),
      topic(2),
      topic(3, { source_count: 8 }),
    ]
    expect(orderedTopics(list).map((t) => t.id)).toEqual([3, 2, 1])
    expect(excludedTopic(topic(4, { article_count: 0 }))).toBe(true)
  })
  it('resonant clusters (source>=3) outrank fresher single-source ones', () => {
    expect(isResonant(topic(9, { source_count: 3 }))).toBe(true)
    expect(isResonant(topic(9, { source_count: 2 }))).toBe(false)
    const list = [
      topic(1, { source_count: 1, updated_at: '2026-09-28T00:00:00Z' }),
      topic(2, { source_count: 5, updated_at: '2026-09-20T00:00:00Z' }),
      topic(3, { source_count: 6, updated_at: '2026-09-19T00:00:00Z' }),
    ]
    expect(orderedTopics(list).map((t) => t.id)).toEqual([3, 2, 1])
  })
  it('searches topic names, entities and keywords, hiding excluded topics by default', () => {
    const list = [
      topic(1, {
        label: 'Agent 安全',
        entities: ['Anthropic'],
        watch_keywords: ['权限'],
      }),
      topic(2, { label: '噪声', entities: ['Anthropic'], status: 'invalid' }),
    ]
    expect(matchingTopics(list, 'anthropic 权限').map((t) => t.id)).toEqual([1])
    expect(matchingTopics(list, 'anthropic', true)).toHaveLength(2)
  })
  it('uses exactly the meaningful unique policy matching terms', () => {
    expect(
      topicPolicyTerms(
        topic(1, {
          entities: [' ', 'AI', 'AI', 'x'],
          watch_keywords: ['安全', 'a'.repeat(61)],
        }),
      ),
    ).toEqual(['AI', '安全'])
  })
  it('omits missing or duplicated article summaries', () => {
    expect(articleTeaser('A title', ' **A title** ')).toBeNull()
    expect(articleTeaser('A title', null)).toBeNull()
    expect(articleTeaser('A title', 'A useful summary')).toBe(
      'A useful summary',
    )
  })
})
