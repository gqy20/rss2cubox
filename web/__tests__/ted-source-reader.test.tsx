import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import SourceReader, { SourceAnalysisTitle } from '../app/ted/SourceReader'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
it('loads analysis on demand, keeps citation notes separate, and restores focus on Escape', async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: {
    source: { id: 'source', title: '资料标题', url: 'https://example.org', publisher: '机构', reason: '引用理由' },
    analysis: { kind: 'article', importance_score: 4, reason: '逐篇判断', hidden_signal: '', actionable: '', prediction: '', summary: '', source_quote: '', tags: [] },
    record_id: 'record',
  } }) })
  vi.stubGlobal('fetch', fetch)
  render(<SourceReader issueId="issue"><SourceAnalysisTitle sourceId="source" title="资料标题" /></SourceReader>)
  expect(fetch).not.toHaveBeenCalled()
  const trigger = screen.getByRole('button', { name: '查看AI分析：资料标题' })
  trigger.focus()
  fireEvent.click(trigger)
  expect(await screen.findByText('逐篇判断')).toBeInTheDocument()
  expect(screen.getByText('本期引用说明')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '阅读原文' })).toHaveAttribute('href', 'https://example.org')
  expect(fetch).toHaveBeenCalledWith('/api/ted/issue/source?id=source', expect.objectContaining({ signal: expect.any(AbortSignal) }))
  fireEvent.keyDown(document, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(trigger).toHaveFocus()
  expect(document.body.style.overflow).toBe('')
})
