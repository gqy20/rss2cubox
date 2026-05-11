import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { getFaviconUrl, SourceLogo } from '@/app/utils'
import type { Row } from '@/app/types'

function queryImg(container: HTMLElement) {
  return container.querySelector('img')
}

describe('getFaviconUrl', () => {
  // ── 新增 source 覆盖 ──

  it('为知乎热榜返回 zhihu.com favicon', () => {
    const row: Row = {
      id: '1', title: '', url: 'https://www.zhihu.com/question/123',
      source: '知乎热榜', time: '',
      source_feed: '/zhihu/hot',
    }
    const url = getFaviconUrl(row)
    expect(url).toContain('zhihu.com')
    expect(url).toContain('sz=32')
  })

  it('为 Solidot 返回 solidot.org favicon', () => {
    const row: Row = {
      id: '2', title: '', url: 'https://www.solidot.org/story?sid=84255',
      source: 'Solidot 科技新闻', time: '',
      source_feed: '/solidot',
    }
    const url = getFaviconUrl(row)
    expect(url).toContain('solidot.org')
    expect(url).toContain('sz=32')
  })

  it('为 36kr 返回 36kr.com favicon', () => {
    const row: Row = {
      id: '3', title: '', url: 'https://36kr.com/p/123',
      source: '36氪', time: '',
      source_feed: '/36kr',
    }
    const url = getFaviconUrl(row)
    expect(url).toContain('36kr.com')
    expect(url).toContain('sz=32')
  })

  it('为 V2EX 返回 v2ex.com favicon', () => {
    const row: Row = {
      id: '4', title: '', url: 'https://www.v2ex.com/t/123',
      source: 'V2EX', time: '',
      source_feed: '/v2ex',
    }
    const url = getFaviconUrl(row)
    expect(url).toContain('v2ex.com')
    expect(url).toContain('sz=32')
  })

  // ── GitHub releases 特殊处理 ──

  it('GitHub releases feed 使用组织 avatar 而非通用 github favicon', () => {
    const row: Row = {
      id: '5', title: '', url: 'https://github.com/openai/codex/releases/tag/v1',
      source: 'OpenAI Codex', time: '',
      source_feed: 'https://github.com/openai/codex/releases.atom',
    }
    const url = getFaviconUrl(row)
    // 应该包含组织名，而非通用 github.com favicon
    expect(url).toContain('openai')
    expect(url).not.toContain('s2/favicons')
  })

  it('GitHub releases 从 URL 回退时也能提取组织名', () => {
    const row: Row = {
      id: '6', title: '', url: 'https://github.com/anomalyco/opencode/releases/tag/v1',
      source: 'OpenCode', time: '',
      source_feed: 'https://github.com/anomalyco/opencode/releases.atom',
    }
    const url = getFaviconUrl(row)
    expect(url).toContain('anomalyco')
  })

  // ── Fallback 占位符 ──

  it('未知 source 不再返回空字符串，而是返回默认 RSS 图标 URL', () => {
    const row: Row = {
      id: '7', title: '', url: 'https://unknown-source.example.com/article',
      source: '完全未知的源', time: '',
      source_feed: '/unknown/path',
    }
    const url = getFaviconUrl(row)
    expect(url).not.toBe('')
    // 应该是 Google favicon 或其他有效 URL
    expect(url).toMatch(/^https?:\/\//)
  })

  // ── 尺寸统一为 sz=32 ──

  it('所有 favicon URL 统一使用 sz=32', () => {
    const cases: Array<Partial<Row>> = [
      { source_feed: 'https://openai.com/blog/rss.xml' },
      { source_feed: '/hackernews', source: 'Hacker News', source_label: 'Hacker News' },
      { source_feed: '/juejin/posts/1', url: 'https://juejin.cn/post/1' },
      { source_feed: '/bilibili/1', url: 'https://www.bilibili.com/video/BV1' },
      { source_feed: 'https://developer.nvidia.com/blog/feed' },
    ]
    for (const base of cases) {
      const row: Row = {
        id: 'x', title: '', url: base.url || '', source: base.source || '',
        time: '', source_feed: base.source_feed || '',
        source_label: (base as any).source_label,
      }
      const url = getFaviconUrl(row)
      if (url) expect(url).toContain('sz=32')
    }
  })

  // ── 回归：已有 source 仍然正常 ──

  it('OpenAI blog feed 正常匹配', () => {
    const row: Row = {
      id: '8', title: '', url: 'https://openai.com/index/test',
      source: 'OpenAI Blog', time: '',
      source_feed: 'https://openai.com/blog/rss.xml',
    }
    const url = getFaviconUrl(row)
    expect(url).toContain('openai.com')
  })

  it('Hacker News 通过 MAP 匹配', () => {
    const row: Row = {
      id: '9', title: '', url: 'http://example.com',
      source: 'Hacker News', time: '',
      source_feed: '/hackernews',
      source_label: 'Hacker News',
    }
    const url = getFaviconUrl(row)
    expect(url).toContain('ycombinator.com')
  })

  it('掘金通过路径前缀匹配', () => {
    const row: Row = {
      id: '10', title: '', url: 'https://juejin.cn/post/1',
      source: '程序员鱼皮', time: '',
      source_feed: '/juejin/posts/2444938365386621',
    }
    const url = getFaviconUrl(row)
    expect(url).toContain('juejin.cn')
  })
})

describe('SourceLogo component', () => {
  it('渲染 favicon img 标签', () => {
    const row: Row = {
      id: 'l1', title: '', url: 'https://example.com',
      source: 'Test Source', time: '',
      source_feed: 'https://example.com/feed.xml',
    }
    const { container } = render(<SourceLogo row={row} />)
    const img = queryImg(container)
    expect(img).not.toBeNull()
    expect(img!).toHaveAttribute('width', '14')
    expect(img!).toHaveAttribute('height', '14')
  })

  it('未知源也渲染图片（fallback）', () => {
    const row: Row = {
      id: 'l2', title: '', url: 'https://unknown.example.com/a',
      source: 'Unknown', time: '',
      source_feed: '/unknown',
    }
    const { container } = render(<SourceLogo row={row} />)
    // fallback 后应该有 img（不再返回 null）
    expect(queryImg(container)).not.toBeNull()
  })
})
