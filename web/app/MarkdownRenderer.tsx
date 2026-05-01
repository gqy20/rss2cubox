'use client'

import type { ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'

type MarkdownRendererProps = {
  children?: ReactNode
  /** 默认 false；设为 true 时禁用段落包裹（适合内联场景如标题行） */
  inline?: boolean
}

/**
 * 统一的 Markdown 渲染组件。
 * 用于 AI 生成的信号文本（洞察、核心事件、建议、分析等）。
 */
const mdComponents: Components = {
  h1: ({ children }) => <h1 style={{ fontSize: 16, fontWeight: 700, margin: '8px 0 4px', color: '#eef3fa' }}>{children}</h1>,
  h2: ({ children }) => <h2 style={{ fontSize: 15, fontWeight: 700, margin: '6px 0 3px', color: '#eef3fa' }}>{children}</h2>,
  h3: ({ children }) => <h3 style={{ fontSize: 14, fontWeight: 600, margin: '4px 0 2px', color: '#e2e8f0' }}>{children}</h3>,
  p: ({ children }) => <p style={{ margin: '3px 0', lineHeight: 1.55 }}>{children}</p>,
  strong: ({ children }) => <strong style={{ fontWeight: 700 }}>{children}</strong>,
  em: ({ children }) => <em>{children}</em>,
  code: ({ children, className }) =>
    className ? (
      <code className={className} style={{ display: 'block', background: 'rgba(15, 23, 42, 0.7)', borderRadius: 6, padding: '8px 12px', fontSize: 12, lineHeight: 1.5, overflowX: 'auto' }}>
        {children}
      </code>
    ) : (
      <code style={{ background: 'rgba(99, 110, 123, 0.22)', borderRadius: 3, padding: '1px 5px', fontSize: '0.88em', color: '#c9d1d9' }}>
        {children}
      </code>
    ),
  ul: ({ children }) => <ul style={{ paddingLeft: 18, margin: '4px 0' }}>{children}</ul>,
  ol: ({ children }) => <ol style={{ paddingLeft: 18, margin: '4px 0' }}>{children}</ol>,
  li: ({ children }) => <li style={{ marginBottom: 2, lineHeight: 1.5 }}>{children}</li>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: '#2dd4bf', textDecoration: 'underline', textDecorationColor: 'rgba(45, 212, 191, 0.35)' }}>
      {children}
    </a>
  ),
  blockquote: ({ children }) => (
    <blockquote style={{ borderLeft: '3px solid rgba(79, 209, 197, 0.4)', padding: '4px 10px', margin: '6px 0', background: 'rgba(17, 23, 32, 0.5)', borderRadius: '0 4px 4px 0', color: '#a2aec0' }}>
      {children}
    </blockquote>
  ),
  hr: () => <hr style={{ border: 'none', borderTop: '1px solid rgba(178, 190, 205, 0.12)', margin: '8px 0' }} />,
  table: ({ children }) => (
    <div style={{ overflowX: 'auto', margin: '6px 0' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>{children}</table>
    </div>
  ),
  th: ({ children }) => <th style={{ padding: '4px 8px', borderBottom: '1px solid rgba(178, 190, 205, 0.2)', textAlign: 'left', color: '#aeb9c8', fontWeight: 600 }}>{children}</th>,
  td: ({ children }) => <td style={{ padding: '4px 8px', borderBottom: '1px solid rgba(178, 190, 205, 0.08)', color: '#e2e8f0' }}>{children}</td>,
  del: ({ children }) => <del style={{ color: '#8aa3be' }}>{children}</del>,
}

function extractText(children: ReactNode): string | null {
  if (children == null) return null
  if (typeof children === 'string') return children.trim() || null
  if (typeof children === 'number') return String(children)
  if (Array.isArray(children)) {
    const parts = children.map(extractText).filter((v): v is string => v != null)
    const joined = parts.join('')
    return joined.trim() || null
  }
  // ReactElement — 取其 props.children 递归提取
  if (typeof children === 'object' && 'props' in children) {
    return extractText((children as React.JSX.Element).props.children)
  }
  return null
}

export default function MarkdownRenderer({ children, inline }: MarkdownRendererProps) {
  const text = extractText(children)
  if (!text) return null

  if (inline) {
    return (
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
        {text}
      </ReactMarkdown>
    )
  }

  return (
    <div className="md-content">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
        {text}
      </ReactMarkdown>
    </div>
  )
}
