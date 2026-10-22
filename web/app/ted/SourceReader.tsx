'use client'
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import Drawer from '../journal/Drawer'
import MarkdownRenderer from '../MarkdownRenderer'
import { ScoreIndicator } from '../journal/Numbers'
import { httpUrl, type TedSourceDetail } from '../../lib/ted'

const OpenSource = createContext<((id: string, title: string) => void) | null>(null)

export function SourceAnalysisTitle({ sourceId, title, className }: { sourceId: string; title: string; className?: string }) {
  const open = useContext(OpenSource)
  return <button type="button" className={className} onClick={() => open?.(sourceId, title)} title={`${title}（查看AI分析）`} aria-label={`查看AI分析：${title}`}>{title}</button>
}

export default function SourceReader({ issueId, children }: { issueId: string; children: ReactNode }) {
  const [selected, setSelected] = useState<{ id: string; title: string } | null>(null)
  const [data, setData] = useState<TedSourceDetail | null>(null)
  const [error, setError] = useState(''), [loading, setLoading] = useState(false), [retry, setRetry] = useState(0)
  const open = useCallback((id: string, title: string) => { setSelected({ id, title }); setData(null); setError('') }, [])
  const close = useCallback(() => setSelected(null), [])
  useEffect(() => {
    if (!selected) return
    const controller = new AbortController()
    setLoading(true); setData(null); setError('')
    fetch(`/api/ted/${issueId}/source?id=${encodeURIComponent(selected.id)}`, { signal: controller.signal })
      .then(async (response) => {
        const body = await response.json()
        if (!response.ok) throw new Error(body.error || '资料暂时不可用。')
        if (!controller.signal.aborted) setData(body.data)
      })
      .catch((error) => { if (!controller.signal.aborted) setError(error.message || '资料暂时不可用。') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [issueId, selected, retry])
  const analysis = data?.analysis
  const sections = analysis ? [
    [analysis.kind === 'policy' ? '相关性判断' : '为何重要', analysis.reason],
    ['隐藏信号', analysis.hidden_signal], ['行动建议', analysis.actionable],
    ['趋势预测', analysis.prediction], ['政策摘要', analysis.summary], ['原文引句', analysis.source_quote],
  ].filter(([, text]) => Boolean(text)) : []
  return <OpenSource.Provider value={open}>
    {children}
    {selected && createPortal(
      <Drawer open onClose={close} label="资料AI分析" header={<div className="ted-analysis-heading">
        <h2>{data?.source.title || selected.title}</h2>
        <div className="metadata">{data?.source.publisher && <span>{data.source.publisher}</span>}
          {data && httpUrl(data.source.url) && <a className="text-link" href={data.source.url} target="_blank" rel="noopener noreferrer">阅读原文</a>}
        </div>
      </div>}>
        <div className="ted-analysis-content">
          {loading && <div className="loading-skeleton" role="status" aria-label="正在读取分析" />}
          {error && <div role="alert"><p>{error}</p><button className="soft-button" onClick={() => setRetry((n) => n + 1)}>重试</button></div>}
          {!loading && !error && data && <>
            {analysis?.importance_score != null && <ScoreIndicator label="重要性" value={analysis.importance_score} />}
            {analysis?.ai_relevance != null && <ScoreIndicator label="AI相关度" value={analysis.ai_relevance} />}
            {sections.map(([title, text]) => <section key={title}><h3>{title}</h3><MarkdownRenderer>{text}</MarkdownRenderer></section>)}
            {!sections.length && <p className="muted-text">这篇资料暂无逐篇AI分析。</p>}
            {data.source.reason && <section><h3>本期引用说明</h3><p>{data.source.reason}</p></section>}
            {!!analysis?.tags.length && <div className="ted-tags">{analysis.tags.map((tag) => <span className="pill clay" key={tag}>{tag}</span>)}</div>}
          </>}
        </div>
      </Drawer>, document.body,
    )}
  </OpenSource.Provider>
}
