import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  buildApiUrl,
  normalizeSource,
  normalizeTime,
  normalizeArticle,
  fetchAllArticles,
  type IcArticle,
} from '@/lib/icApi'

// Mock fetch globally
const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

beforeEach(() => {
  vi.clearAllMocks()
  // Default: process.env not available in vitest, we'll pass URL explicitly
})

describe('buildApiUrl', () => {
  it('should build correct API URL with limit and offset', () => {
    const url = buildApiUrl(50, 0, 'https://api.example.com/api/v1/articles/batch/', 'gqy')
    expect(url).toContain('limit=50')
    expect(url).toContain('offset=0')
    expect(url).toContain('source_type=gqy')
    expect(url).toContain('/api/v1/articles')
  })

  it('should strip /batch/ suffix from base URL', () => {
    const url = buildApiUrl(100, 200, 'https://api.example.com/api/v1/articles/batch/', 'gqy')
    expect(url).not.toContain('/batch/')
    expect(url).toBe('https://api.example.com/api/v1/articles?limit=100&offset=200&source_type=gqy')
  })

  it('should return empty string when base URL is empty', () => {
    const url = buildApiUrl(50, 0, '', 'gqy')
    expect(url).toBe('')
  })

  it('should preserve a path prefix on the base URL', () => {
    const url = buildApiUrl(50, 0, 'https://api.example.com/base', 'gqy')
    expect(url).toBe('https://api.example.com/base/api/v1/articles?limit=50&offset=0&source_type=gqy')
  })
})

describe('normalizeSource', () => {
  it('should return source_feed_name when available', () => {
    const article = { source_feed_name: 'Hacker News' } as IcArticle
    expect(normalizeSource(article)).toBe('Hacker News')
  })

  it('should extract hostname from source_feed_id when it is a URL', () => {
    const article = { source_feed_name: '', source_feed_id: 'https://feeds.feedburner.com/tech' } as IcArticle
    expect(normalizeSource(article)).toBe('feeds.feedburner.com')
  })

  it('should return source_feed_id as-is when not a valid URL', () => {
    const article = { source_feed_name: '', source_feed_id: '/bilibili/tech' } as IcArticle
    expect(normalizeSource(article)).toBe('/bilibili/tech')
  })

  it('should extract hostname from article URL as fallback', () => {
    const article = { source_feed_name: '', source_feed_id: '', url: 'https://arxiv.org/abs/2401.00001' } as IcArticle
    expect(normalizeSource(article)).toBe('arxiv.org')
  })

  it('should return unknown when no source info available', () => {
    const article = {} as IcArticle
    expect(normalizeSource(article)).toBe('unknown')
  })
})

describe('normalizeTime', () => {
  it('should prefer publish_time over created_at', () => {
    const article = { publish_time: '2025-01-15T10:30:00', created_at: '2025-01-01T00:00:00' } as IcArticle
    expect(normalizeTime(article)).toBe('2025-01-15T10:30:00')
  })

  it('should fall back to created_at when publish_time missing', () => {
    const article = { publish_time: null, created_at: '2025-01-01T00:00:00' } as IcArticle
    expect(normalizeTime(article)).toBe('2025-01-01T00:00:00')
  })

  it('should return empty string when both missing', () => {
    const article = {} as IcArticle
    expect(normalizeTime(article)).toBe('')
  })
})

describe('normalizeArticle', () => {
  it('should convert IcArticle to EventRow format', () => {
    const input: IcArticle = {
      id: 42,
      title: 'Test Article',
      url: 'https://example.com/article',
      source_feed_id: '/hackernews',
      source_feed_name: 'Hacker News',
      pic_url: 'https://img.example.com/cover.jpg',
      publish_time: '2025-06-01T12:00:00',
      tags: ['tech', 'ai'],
      description: 'Core event text',
      hidden_signal: 'Weak signal',
      actionable: 'Do something',
      reason: 'Analysis result',
    }

    const result = normalizeArticle(input)

    expect(result.id).toBe('42')
    expect(result.title).toBe('Test Article')
    expect(result.url).toBe('https://example.com/article')
    expect(result.source).toBe('Hacker News')
    expect(result.time).toBe('2025-06-01T12:00:00')
    expect(result.cover_url).toBe('https://img.example.com/cover.jpg')
    expect(result.tags).toEqual(['tech', 'ai'])
    expect(result.core_event).toBe('Core event text')
    expect(result.hidden_signal).toBe('Weak signal')
    expect(result.actionable).toBe('Do something')
    expect(result.reason).toBe('Analysis result')
    expect(result.exported).toBe(true)
    expect(result.status).toBe('exported')
  })

  it('should handle null/undefined fields gracefully', () => {
    const input: IcArticle = { id: 1 }
    const result = normalizeArticle(input)

    expect(result.title).toBe('')
    expect(result.url).toBe('')
    expect(result.tags).toEqual([])
    expect(result.core_event).toBe('')
  })
})

describe('fetchAllArticles', () => {
  it('should paginate through all pages and return all articles', async () => {
    // Page 1: returns 2 items (less than batchSize, so stops)
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        data: { list: [{ id: 1 }, { id: 2 }] },
      }),
    })

    const results = await fetchAllArticles(
      'https://api.example.com/api/v1/articles/batch/',
      'gqy'
    )

    expect(results).toHaveLength(2)
    expect(mockFetch).toHaveBeenCalledTimes(1)
  })

  it('should make multiple requests when page is full', async () => {
    // Page 1: full batch → continue; Page 2: partial → stop
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: { list: Array.from({ length: 100 }, (_, i) => ({ id: i })) },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          ok: true,
          data: { list: [{ id: 999 }] },
        }),
      })

    const results = await fetchAllArticles(
      'https://api.example.com/api/v1/articles/batch/',
      'gqy'
    )

    expect(results).toHaveLength(101)
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })

  it('should throw on HTTP error', async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 500 })

    await expect(
      fetchAllArticles('https://api.example.com/api/v1/articles/batch/', 'gqy')
    ).rejects.toThrow('HTTP 500')
  })

  it('should return empty array when base URL is empty', async () => {
    const results = await fetchAllArticles('', 'gqy')
    expect(results).toEqual([])
    expect(mockFetch).not.toHaveBeenCalled()
  })
})
