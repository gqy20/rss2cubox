import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
const navigation = vi.hoisted(() => ({ query: 'search=old' }))
vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(navigation.query),
}))
import Reader from '../../app/journal/Reader'
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
it('ignores a late response for an older keyword, even if abort does not stop the server', async () => {
  const pending: {
    url: string
    resolve: (response: Response) => void
    signal: AbortSignal
  }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(
      (url: string, options: RequestInit) =>
        new Promise<Response>((resolve) =>
          pending.push({ url, resolve, signal: options.signal as AbortSignal }),
        ),
    ),
  )
  vi.stubGlobal('matchMedia', () => ({ matches: false }))
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
    value: vi.fn(),
    configurable: true,
  })
  const view = render(<Reader kind="signals" />)
  navigation.query = 'search=new'
  view.rerender(<Reader kind="signals" />)
  expect(pending).toHaveLength(2)
  expect(pending[0].signal.aborted).toBe(true)
  const response = (title: string) =>
    ({
      ok: true,
      json: async () => ({
        data: [
          {
            id: title,
            title,
            source: 'Test',
            time: '2026-09-19T00:00:00Z',
            url: 'https://example.org',
          },
        ],
        total: 1,
        page: 1,
        hasMore: false,
      }),
    }) as Response
  await act(async () => pending[1].resolve(response('Newest result')))
  expect(
    screen.getByRole('heading', { name: 'Newest result' }),
  ).toBeInTheDocument()
  await act(async () => pending[0].resolve(response('Old result')))
  expect(
    screen.queryByRole('heading', { name: 'Old result' }),
  ).not.toBeInTheDocument()
  expect(
    screen.getByRole('heading', { name: 'Newest result' }),
  ).toBeInTheDocument()
})
