import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest'
const navigation = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock('next/navigation', () => ({ useRouter: () => navigation }))
import TopicSelector from '../../app/journal/TopicSelector'
import type { Cluster } from '../../lib/journal-types'
const topics: Cluster[] = [
  {
    id: 1,
    label: 'Agent 安全',
    status: 'warming',
    summary: null,
    article_count: 20,
    source_count: 8,
    entities: ['Anthropic'],
    watch_keywords: [],
    updated_at: '2026-09-18T00:00:00Z',
  },
  {
    id: 2,
    label: '推理优化',
    status: 'warming',
    summary: null,
    article_count: 10,
    source_count: 4,
    entities: ['CUDA'],
    watch_keywords: [],
    updated_at: '2026-09-18T00:00:00Z',
  },
  {
    id: 3,
    label: '噪声内容',
    status: 'invalid',
    summary: null,
    article_count: 5,
    source_count: 2,
    entities: [],
    watch_keywords: [],
    updated_at: '2026-09-19T00:00:00Z',
  },
]
beforeEach(() => {
  navigation.push.mockClear()
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
describe('topic chooser', () => {
  it('filters long topic names and supports Enter selection', async () => {
    render(<TopicSelector topics={topics} selectedId={1} />)
    fireEvent.click(screen.getByRole('button', { name: /切换专题/ }))
    const input = await screen.findByRole('combobox', { name: '查找专题' })
    expect(screen.getAllByRole('option')).toHaveLength(2)
    fireEvent.change(input, { target: { value: 'CUDA' } })
    expect(screen.getAllByRole('option')).toHaveLength(1)
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(navigation.push).toHaveBeenCalledWith('/topics?id=2', {
      scroll: false,
    })
  })
  it('allows explicitly showing excluded topics without choosing them automatically', async () => {
    render(<TopicSelector topics={topics} selectedId={1} />)
    fireEvent.click(screen.getByRole('button', { name: /切换专题/ }))
    fireEvent.click(
      await screen.findByRole('checkbox', { name: '包含已排除专题' }),
    )
    expect(screen.getAllByRole('option')).toHaveLength(3)
    expect(navigation.push).not.toHaveBeenCalled()
  })
})
