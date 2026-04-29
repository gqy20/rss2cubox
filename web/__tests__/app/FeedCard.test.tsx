import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import FeedCard from '@/app/FeedCard'
import type { Row } from '@/app/types'

describe('FeedCard enrich fields', () => {
  it('surfaces the most actionable enrich metadata', () => {
    const row: Row = {
      id: 'r1',
      title: 'Agent infrastructure shifts',
      url: 'https://example.com/agent',
      source: 'Example',
      time: '2026-04-29T10:00:00.000',
      tags: ['Agent'],
      core_event: '云平台开始提供 Agent runtime。',
      hidden_signal: 'Agent 运行时成为新锁定点。',
      actionable: '评估权限和状态层。',
      reason: '影响企业落地架构。',
      importance_score: 4,
      content_source: 'full_text',
      signal_type: 3,
      evidence_strength: 4,
      novelty_score: 5,
      impact_horizon: 3,
      confidence: 4,
      entities: ['OpenAI', 'AWS'],
      watch_keywords: ['Agent runtime', 'Bedrock'],
      prediction: '未来30天会出现更多云厂商 Agent runtime 集成。',
    }

    render(
      <FeedCard
        row={row}
        idx={0}
        groupId="2026-04-29"
        now={new Date('2026-04-29T10:30:00.000')}
        hoveredRowKey="r1"
        selectedTag={null}
        onHoverEnter={vi.fn()}
        onHoverLeave={vi.fn()}
        onToggleOpen={vi.fn()}
        onTagClick={vi.fn()}
      />,
    )

    expect(screen.getByText('开发者工作流')).toBeInTheDocument()
    expect(screen.getByText('全文')).toBeInTheDocument()
    expect(screen.getByText('证据 4/5')).toBeInTheDocument()
    expect(screen.getByText('新颖 5/5')).toBeInTheDocument()
    expect(screen.getByText('置信 4/5')).toBeInTheDocument()
    expect(screen.getByText('月级影响')).toBeInTheDocument()
    expect(screen.getByText('OpenAI')).toBeInTheDocument()
    expect(screen.getByText('AWS')).toBeInTheDocument()
    expect(screen.getByText('Agent runtime')).toBeInTheDocument()
    expect(screen.getByText('Bedrock')).toBeInTheDocument()
    expect(screen.getByText('未来30天会出现更多云厂商 Agent runtime 集成。')).toBeInTheDocument()
  })

  it('treats entity-only metadata as expandable signal details', () => {
    const row: Row = {
      id: 'r2',
      title: 'Model context protocol update',
      url: 'https://example.com/mcp',
      source: 'Example',
      time: '2026-04-29T10:00:00.000',
      hidden_signal: 'MCP 生态继续扩展。',
      entities: ['MCP', 'OpenAI'],
    }

    render(
      <FeedCard
        row={row}
        idx={0}
        groupId="2026-04-29"
        now={new Date('2026-04-29T10:30:00.000')}
        hoveredRowKey="r2"
        selectedTag={null}
        onHoverEnter={vi.fn()}
        onHoverLeave={vi.fn()}
        onToggleOpen={vi.fn()}
        onTagClick={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { expanded: true })).toBeInTheDocument()
    expect(screen.getByText('收起详情')).toBeInTheDocument()
    expect(screen.getByText('实体')).toBeInTheDocument()
    expect(screen.getByText('MCP')).toBeInTheDocument()
    expect(screen.getByText('OpenAI')).toBeInTheDocument()
    expect(screen.queryByText('追踪')).not.toBeInTheDocument()
  })
})
