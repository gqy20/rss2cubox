import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
const navigation = vi.hoisted(() => ({
  path: '/signals',
  query: '',
  push: vi.fn(),
}))
vi.mock('next/navigation', () => ({
  usePathname: () => navigation.path,
  useSearchParams: () => new URLSearchParams(navigation.query),
  useRouter: () => ({ push: navigation.push }),
}))
import SearchBar from '../../app/journal/SearchBar'
beforeEach(() => {
  navigation.path = '/signals'
  navigation.query = ''
  navigation.push.mockClear()
  vi.useFakeTimers()
  window.history.replaceState(null, '', '/signals')
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})
describe('single search entry', () => {
  it('debounces list searches and clears page and selected item', () => {
    navigation.query = 'mode=high&page=3&id=old'
    const replace = vi.spyOn(window.history, 'replaceState')
    render(<SearchBar />)
    fireEvent.change(screen.getByRole('searchbox'), {
      target: { value: 'Agent' },
    })
    act(() => vi.advanceTimersByTime(349))
    expect(replace).not.toHaveBeenCalled()
    act(() => vi.advanceTimersByTime(1))
    expect(replace).toHaveBeenLastCalledWith(
      null,
      '',
      '/signals?mode=high&search=Agent',
    )
  })
  it('does not query while Chinese text is being composed or submit its Enter key', () => {
    const replace = vi.spyOn(window.history, 'replaceState'),
      push = vi.spyOn(window.history, 'pushState')
    render(<SearchBar />)
    const input = screen.getByRole('searchbox')
    fireEvent.compositionStart(input)
    fireEvent.change(input, { target: { value: 'zheng' } })
    fireEvent.keyDown(input, { key: 'Enter', isComposing: true, keyCode: 229 })
    act(() => vi.advanceTimersByTime(1000))
    expect(replace).not.toHaveBeenCalled()
    expect(push).not.toHaveBeenCalled()
    fireEvent.change(input, { target: { value: '政策' } })
    fireEvent.compositionEnd(input, { data: '政策' })
    act(() => vi.advanceTimersByTime(350))
    expect(replace).toHaveBeenLastCalledWith(
      null,
      '',
      '/signals?search=%E6%94%BF%E7%AD%96',
    )
  })
  it('waits for explicit submit from the homepage and uses the selected scope', () => {
    navigation.path = '/'
    render(<SearchBar />)
    fireEvent.change(screen.getByRole('combobox', { name: '搜索范围' }), {
      target: { value: 'policies' },
    })
    fireEvent.change(screen.getByRole('searchbox'), {
      target: { value: '人工智能' },
    })
    act(() => vi.advanceTimersByTime(1000))
    expect(navigation.push).not.toHaveBeenCalled()
    fireEvent.submit(screen.getByRole('search'))
    expect(navigation.push).toHaveBeenCalledWith(
      '/policies?search=%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD',
    )
  })
  it('clears the query immediately while preserving filters', () => {
    navigation.query = 'search=AI&mode=high&page=2'
    const replace = vi.spyOn(window.history, 'replaceState')
    render(<SearchBar />)
    fireEvent.click(screen.getByRole('button', { name: '清空搜索' }))
    expect(replace).toHaveBeenLastCalledWith(null, '', '/signals?mode=high')
    expect(screen.getByRole('searchbox')).toHaveValue('')
  })
  it('cancels a pending query on Escape', () => {
    navigation.query = 'search=AI'
    const replace = vi.spyOn(window.history, 'replaceState')
    render(<SearchBar />)
    fireEvent.change(screen.getByRole('searchbox'), {
      target: { value: 'new' },
    })
    fireEvent.keyDown(screen.getByRole('searchbox'), { key: 'Escape' })
    act(() => vi.advanceTimersByTime(500))
    expect(replace).not.toHaveBeenCalled()
    expect(screen.getByRole('searchbox')).toHaveValue('AI')
  })
})
