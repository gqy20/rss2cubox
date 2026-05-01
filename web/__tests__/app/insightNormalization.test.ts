import { describe, it, expect } from 'vitest'

// ── 纯函数：从后端新格式归一化为前端展示格式 ──────────────────

/** 后端 global_agent 新输出的单条信号 */
type BackendSignalItem = {
  text: string
  source_urls?: string[]
  source_titles?: string[]
}

/** 前端展示用的归一化条目 */
interface NormalizedInsightItem {
  title: string
  content?: string
  sourceUrls?: string[]
  sourceTitles?: string[]
}

/**
 * 归一化后端 insight 数据。
 * 兼容三种输入：
 *   - 新格式: { text, source_urls?, source_titles? }
 *   - 旧格式: 纯字符串
 *   - 旧对象格式: { title, content? } （已废弃，兼容）
 */
function normalizeInsightItems(raw: unknown[]): NormalizedInsightItem[] {
  return raw
    .map((item): NormalizedInsightItem | null => {
      if (typeof item === 'string') {
        const t = item.trim()
        return t.length > 0 ? { title: t } : null
      }

      if (!item || typeof item !== 'object') return null

      const obj = item as Record<string, unknown>

      // 新格式：{ text, source_urls?, source_titles? }
      if ('text' in obj && typeof obj.text === 'string') {
        const text = obj.text.trim()
        if (!text) return null
        const urls = Array.isArray(obj.source_urls)
          ? obj.source_urls.filter((u): u is string => typeof u === 'string' && Boolean(u.trim()))
          : []
        const titles = Array.isArray(obj.source_titles)
          ? obj.source_titles.filter((t): t is string => typeof t === 'string' && Boolean(t.trim()))
          : []
        return { title: text, sourceUrls: urls, sourceTitles: titles }
      }

      // 旧对象格式：{ title, content? }
      const title = String(obj.title ?? '').trim()
      const content = String(obj.content ?? '').trim()
      if (title) return { title, content: content || undefined }
      if (content) return { title: content }
      return null
    })
    .filter((item): item is NormalizedInsightItem => item !== null)
}

// ── 测试 ───────────────────────────────────────────────────────────────

describe('normalizeInsightItems', () => {
  describe('新格式 {text, source_urls, source_titles}', () => {
    it('完整字段全部提取', () => {
      const result = normalizeInsightItems([
        { text: '多模态推理成为新战场', source_urls: ['https://a.com'], source_titles: ['文章A'] },
      ])

      expect(result).toHaveLength(1)
      expect(result[0].title).toBe('多模态推理成为新战场')
      expect(result[0].sourceUrls).toEqual(['https://a.com'])
      expect(result[0].sourceTitles).toEqual(['文章A'])
    })

    it('只有 text 时 sourceUrls/sourceTitles 为空数组', () => {
      const result = normalizeInsightItems([{ text: '纯文本结论' }])

      expect(result[0].title).toBe('纯文本结论')
      expect(result[0].sourceUrls).toEqual([])
      expect(result[0].sourceTitles).toEqual([])
    })

    it('多条来源正确保留', () => {
      const result = normalizeInsightItems([
        {
          text: '趋势',
          source_urls: ['https://a.com', 'https://b.com', 'https://c.com'],
          source_titles: ['标题A', '标题B', '标题C'],
        },
      ])

      expect(result[0].sourceUrls).toHaveLength(3)
      expect(result[0].sourceTitles).toHaveLength(3)
    })

    it('过滤空字符串 URL 和非字符串值', () => {
      const result = normalizeInsightItems([
        {
          text: 'test',
          source_urls: ['https://valid.com', '', null, 123, '  '] as unknown[],
          source_titles: ['有效标题'] as unknown[],
        },
      ])

      expect(result[0].sourceUrls).toEqual(['https://valid.com'])
    })

    it('text 为空时过滤掉该条目', () => {
      const result = normalizeInsightItems([{ text: '', source_urls: ['https://x.com'] }])
      expect(result).toHaveLength(0)
    })
  })

  describe('旧格式兼容（纯字符串）', () => {
    it('字符串数组正常转换', () => {
      const result = normalizeInsightItems(['趋势A', '趋势B'])

      expect(result).toHaveLength(2)
      expect(result[0].title).toBe('趋势A')
      expect(result[0].sourceUrls).toBeUndefined()
      expect(result[1].title).toBe('趋势B')
    })

    it('空字符串被过滤', () => {
      const result = normalizeInsightItems(['有效', '', '  '])
      expect(result).toHaveLength(1)
    })
  })

  describe('旧格式兼容（{title, content} 对象）', () => {
    it('旧对象格式正常转换', () => {
      const result = normalizeInsightItems([{ title: '旧标题', content: '旧内容' }])

      expect(result).toHaveLength(1)
      expect(result[0].title).toBe('旧标题')
      expect(result[0].content).toBe('旧内容')
    })
  })

  describe('混合格式', () => {
    it('同一数组中混合新旧格式', () => {
      const result = normalizeInsightItems([
        { text: '新格式', source_urls: ['https://x.com'], source_titles: ['X'] },
        '旧格式字符串',
        { title: '旧对象', content: '内容' },
        '',
        null,
      ] as unknown[])

      expect(result).toHaveLength(3)
      expect(result[0].title).toBe('新格式')
      expect(result[0].sourceUrls).toEqual(['https://x.com'])
      expect(result[1].title).toBe('旧格式字符串')
      expect(result[2].title).toBe('旧对象')
    })
  })

  describe('边界情况', () => {
    it('空数组返回空', () => {
      expect(normalizeInsightItems([])).toEqual([])
    })

    it('null/undefined/数字等非法值被过滤', () => {
      const result = normalizeInsightItems([null, undefined, 42, true, {}] as unknown[])
      expect(result).toHaveLength(0)
    })
  })
})

// 导出供其他测试或实现引用
export { normalizeInsightItems }
export type { BackendSignalItem, NormalizedInsightItem }
