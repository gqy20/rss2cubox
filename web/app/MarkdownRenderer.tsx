'use client'

import type { ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'

type MarkdownRendererProps = {
  children?: ReactNode
  /** 默认 false；设为 true 时块级元素（p/h1-h3等）降级为内联展示 */
  inline?: boolean
}

/** 共享的行内级组件样式 */
const sharedComponents: Components = {
  strong: ({ children }) => <strong className="md-strong">{children}</strong>,
  em: ({ children }) => <em className="md-em">{children}</em>,
  code: ({ children, className }) =>
    className ? (
      <code className={`md-code-block ${className}`}>{children}</code>
    ) : (
      <code className="md-code">{children}</code>
    ),
  ul: ({ children }) => <ul className="md-ul">{children}</ul>,
  ol: ({ children }) => <ol className="md-ol">{children}</ol>,
  li: ({ children }) => <li className="md-li">{children}</li>,
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="md-a">
      {children}
    </a>
  ),
  blockquote: ({ children }) => (
    <blockquote className="md-blockquote">{children}</blockquote>
  ),
  hr: () => <hr className="md-hr" />,
  table: ({ children }) => (
    <div className="md-table-wrap">
      <table className="md-table">{children}</table>
    </div>
  ),
  th: ({ children }) => <th className="md-th">{children}</th>,
  td: ({ children }) => <td className="md-td">{children}</td>,
  del: ({ children }) => <del className="md-del">{children}</del>,
}

/** 块级模式：保留 h1-h3 / p 等块级标签 */
const blockComponents: Components = {
  ...sharedComponents,
  h1: ({ children }) => <h1 className="md-h1">{children}</h1>,
  h2: ({ children }) => <h2 className="md-h2">{children}</h2>,
  h3: ({ children }) => <h3 className="md-h3">{children}</h3>,
  p: ({ children }) => <p className="md-p">{children}</p>,
}

/** 内联模式：h/p 降级为 span，避免块级元素嵌套在行内容器中 */
const inlineComponents: Components = {
  ...sharedComponents,
  h1: ({ children }) => <span className="md-inline-h1">{children}</span>,
  h2: ({ children }) => <span className="md-inline-h2">{children}</span>,
  h3: ({ children }) => <span className="md-inline-h3">{children}</span>,
  p: ({ children }) => <span className="md-inline-p">{children}</span>,
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
  if (typeof children === 'object' && 'props' in children) {
    return extractText((children as React.JSX.Element).props.children)
  }
  return null
}

export default function MarkdownRenderer({ children, inline }: MarkdownRendererProps) {
  const text = extractText(children)
  if (!text) return null

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={inline ? inlineComponents : blockComponents}>
      {text}
    </ReactMarkdown>
  )
}
