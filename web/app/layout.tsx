import './globals.css'
import type { Metadata } from 'next'
import type { ReactNode } from 'react'
import Shell from './journal/Shell'

export const metadata: Metadata = {
  title: 'RSS2Cubox · 技术与政策简报',
  description: '在技术进展与政策变化之间，阅读证据、追踪判断。',
  icons: { icon: '/logo.svg', shortcut: '/logo.svg' },
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </head>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  )
}
