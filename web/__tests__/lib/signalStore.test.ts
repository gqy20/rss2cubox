import { describe, it, expect, vi } from 'vitest'
import { loadIcArticles, loadGlobalInsights } from '@/lib/signalStore'

// Mock fetch for signalStore tests
const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

describe('loadIcArticles (refactored to use icApi)', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('should return empty array when IC_API_URL is not set', async () => {
    // When env var is empty, should return []
    const originalUrl = process.env.IC_API_URL
    process.env.IC_API_URL = ''
    const result = await loadIcArticles()
    expect(result).toEqual([])
    if (originalUrl !== undefined) process.env.IC_API_URL = originalUrl
  })

  it('should return normalized EventRow array from API', async () => {
    // Temporarily set the env var
    const originalUrl = process.env.IC_API_URL
    process.env.IC_API_URL = 'https://api.test.com/api/v1/articles/batch/'

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          list: [
            {
              id: 100,
              title: 'Test Article',
              url: 'https://example.com/test',
              source_feed_id: '/hn',
              source_feed_name: 'Hacker News',
              pic_url: 'https://img.example.com/cover.jpg',
              publish_time: '2025-06-01T12:00:00',
              tags: ['tech'],
              description: 'Core event',
              hidden_signal: 'Weak signal',
              actionable: 'Try it',
              reason: 'Important',
            },
          ],
        },
      }),
    })

    const result = await loadIcArticles()

    expect(result).toHaveLength(1)
    expect(result[0]).toMatchObject({
      id: '100',
      title: 'Test Article',
      source: 'Hacker News',
      time: '2025-06-01T12:00:00',
      core_event: 'Core event',
      hidden_signal: 'Weak signal',
      tags: ['tech'],
    })

    // Restore
    if (originalUrl !== undefined) process.env.IC_API_URL = originalUrl
    else delete process.env.IC_API_URL
  })
})

describe('loadGlobalInsights', () => {
  it('should return null when NEON_DATABASE_URL is not set', async () => {
    const originalUrl = process.env.NEON_DATABASE_URL
    process.env.NEON_DATABASE_URL = ''
    const result = await loadGlobalInsights()
    expect(result).toBeNull()
    if (originalUrl !== undefined) process.env.NEON_DATABASE_URL = originalUrl
  })
})
