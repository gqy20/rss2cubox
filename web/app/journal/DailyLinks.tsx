'use client'
import { useState } from 'react'
import { ExternalLink } from 'lucide-react'
import DailyArticleDrawer from './DailyArticleDrawer'

/**
 * 日报链接交互层（客户端）：
 * - 「分析」pill → 右侧滑出面板（不跳页）
 * - 来源名 → 外链原文（溯源）
 * 把 server 渲染的链接换成这套交互，保持 daily 页其余部分 RSC。
 */
export function AnalyzeLink({ articleId }: { articleId: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        className="daily-source-internal"
        onClick={() => setOpen(true)}
        title="查看我们的分析（右侧展开）"
      >
        分析
      </button>
      {open && (
        <DailyArticleDrawer articleId={articleId} onClose={() => setOpen(false)} />
      )}
    </>
  )
}

export function ArticleTitleAnalyze({
  articleId,
  children,
}: {
  articleId: string
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        className="daily-title-analyze"
        onClick={() => setOpen(true)}
        title="查看分析（右侧展开）"
      >
        {children}
      </button>
      {open && (
        <DailyArticleDrawer articleId={articleId} onClose={() => setOpen(false)} />
      )}
    </>
  )
}

/** 来源名（外链）的客户端包装仅为样式一致，实际是纯 <a>，在 server 端渲染即可 */
export function SourceExternalLink({
  url,
  name,
}: {
  url: string
  name: string
}) {
  return (
    <a href={url} target="_blank" rel="noreferrer">
      {name} <ExternalLink size={11} />
    </a>
  )
}
