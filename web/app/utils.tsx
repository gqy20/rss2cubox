'use client'

import { useState, useEffect } from 'react'
import type { Row } from './types'
import { BUSINESS_TZ, getBusinessDayKey, parseBusinessDate } from '../lib/time'

export const DISPLAY_TZ = 'Asia/Shanghai'

export const PIE_COLORS = ['#2dd4bf', '#60a5fa', '#818cf8', '#a78bfa', '#c084fc']

export const SOURCE_DOMAIN_MAP: Array<[string, string]> = [
  ['hacker news', 'news.ycombinator.com'],
  ['hackernews', 'news.ycombinator.com'],
  ['infoq', 'infoq.cn'],
  ['anthropic', 'anthropic.com'],
  ['openai', 'openai.com'],
  ['cursor', 'cursor.sh'],
  ['youtube', 'youtube.com'],
  ['掘金', 'juejin.cn'],
  ['少数派', 'sspai.com'],
  ['量子位', 'qbitai.com'],
  ['橘鸦', 'juejin.cn'],
  ['github', 'github.com'],
  ['google', 'google.com'],
  ['hugging face', 'huggingface.co'],
  ['huggingface', 'huggingface.co'],
  ['arxiv', 'arxiv.org'],
  ['bair', 'bair.berkeley.edu'],
  ['bilibili', 'bilibili.com'],
  ['微信', 'weixin.qq.com'],
  ['werss', 'weixin.qq.com'],
  ['nvidia', 'nvidia.com'],
  ['marktechpost', 'marktechpost.com'],
  ['gradientflow', 'substack.com'],
  ['deepmind', 'deepmind.google'],
  ['latent space', 'latent.space'],
  ['distill', 'distill.pub'],
  ['知乎', 'zhihu.com'],
  ['solidot', 'solidot.org'],
  ['36氪', '36kr.com'],
  ['36kr', '36kr.com'],
  ['v2ex', 'v2ex.com'],
]

export function formatRelativeTime(value: string, now: Date | null): string {
  const dt = parseBusinessDate(value)
  if (Number.isNaN(dt.getTime())) return value
  if (!now) return dt.toLocaleString('zh-CN', { timeZone: DISPLAY_TZ, month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  const diff = now.getTime() - dt.getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins}分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}小时前`
  return `${Math.floor(hours / 24)}天前`
}

export function formatShortTime(value: string): string {
  const dt = parseBusinessDate(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString('zh-CN', { timeZone: DISPLAY_TZ, hour: '2-digit', minute: '2-digit' })
}

export function getDayKey(value: string | Date): string {
  return getBusinessDayKey(value)
}

export function formatAxisDay(value: Date): string {
  return value.toLocaleDateString('zh-CN', { timeZone: BUSINESS_TZ, month: 'numeric', day: 'numeric' })
}

export function formatGroupTitle(dayKey: string, todayKey: string, yesterdayKey: string): string {
  if (dayKey === todayKey) return '今天'
  if (dayKey === yesterdayKey) return '昨天'
  const [year, month, day] = dayKey.split('-')
  if (!year || !month || !day) return dayKey
  return `${Number(month)}月${Number(day)}日`
}

export function formatKpiDelta(current: number, previous: number): { text: string; trend: 'up' | 'down' | 'flat' } {
  const diff = current - previous
  if (diff === 0) return { text: '持平 vs 昨日', trend: 'flat' }
  if (previous <= 0) {
    return { text: `${diff > 0 ? '↑' : '↓'} ${diff > 0 ? '+' : ''}${diff} vs 昨日`, trend: diff > 0 ? 'up' : 'down' }
  }
  const percent = Math.round((Math.abs(diff) / previous) * 100)
  return {
    text: `${diff > 0 ? '↑' : '↓'} ${percent}% vs 昨日`,
    trend: diff > 0 ? 'up' : 'down',
  }
}

const FAVICON_SIZE = 32

function googleFavicon(domain: string): string {
  return `https://www.google.com/s2/favicons?domain=${domain}&sz=${FAVICON_SIZE}`
}

function extractGithubOrg(feed: string, url: string): string | null {
  const GITHUB_SKIP = new Set(['releases', 'features', 'discussions', 'tags', 'notifications'])
  for (const target of [feed, url]) {
    const m = target.match(/github\.com\/([^/]+)\//i)
    if (m && !GITHUB_SKIP.has(m[1])) return m[1]
  }
  return null
}

function parseHost(raw: string): string | null {
  try {
    return new URL(raw).hostname.replace(/^(rss|feeds?|www)\./i, '')
  } catch {
    return null
  }
}

export function getFaviconUrl(row: Row): string {
  const feed = row.source_feed || ''

  // bilibili
  if (feed.startsWith('/bilibili/') || /bilibili\.com/i.test(row.url || '')) {
    return googleFavicon('bilibili.com')
  }

  // 微信/WeRsS
  if (/werss\.gqy25\.top/i.test(feed) || /weixin\.qq\.com/i.test(feed) || /weixin\.qq\.com/i.test(row.url || '')) {
    return googleFavicon('weixin.qq.com')
  }

  // NVIDIA
  if (/nvidia\.com/i.test(feed) || /nvidia\.com/i.test(row.url || '')) {
    return googleFavicon('nvidia.com')
  }

  // 掘金
  if (feed.startsWith('/juejin/') || /juejin\.cn/i.test(feed) || /juejin\.cn/i.test(row.url || '')) {
    return googleFavicon('juejin.cn')
  }

  // GitHub releases → 组织 avatar（优先 feed URL，回退到 article URL）
  if (
    (feed.includes('github.com') && /releases\.atom|releases\/tag/i.test(feed)) ||
    (/github\.com/i.test(row.url || '') && /releases\/tag/i.test(row.url || ''))
  ) {
    const org = extractGithubOrg(feed, row.url || '')
    if (org) {
      return `https://github.com/${org}.png?s=${FAVICON_SIZE}`
    }
  }

  // HTTP feed URL → 解析 hostname
  if (feed.startsWith('http')) {
    const host = parseHost(feed)
    if (host === 'github.com') {
      const org = extractGithubOrg(feed, row.url || '')
      if (org) return `https://github.com/${org}.png?s=${FAVICON_SIZE}`
    }
    if (host) return googleFavicon(host)
  }

  // SOURCE_DOMAIN_MAP 模糊匹配
  const label = (row.source_label || row.source || '').toLowerCase()
  for (const [key, domain] of SOURCE_DOMAIN_MAP) {
    if (label.includes(key)) {
      return googleFavicon(domain)
    }
  }

  // Fallback：从 URL 提取域名
  const urlHost = parseHost(row.url || '')
  if (urlHost) return googleFavicon(urlHost)

  // 最终 fallback：默认 RSS 图标
  return googleFavicon('example.com')
}

export function Logo({ size = 36 }: { size?: number }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 64 64" fill="none">
      <defs>
        <linearGradient id="lg1" x1="0" y1="0" x2="64" y2="64" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#2dd4bf" />
          <stop offset="100%" stopColor="#60a5fa" />
        </linearGradient>
        <linearGradient id="lg2" x1="0" y1="0" x2="64" y2="64" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#2dd4bf" stopOpacity="0.12" />
          <stop offset="100%" stopColor="#60a5fa" stopOpacity="0.12" />
        </linearGradient>
      </defs>
      <circle cx="32" cy="32" r="31" fill="url(#lg2)" stroke="url(#lg1)" strokeWidth="1" />
      <path d="M 14 50 A 26 26 0 0 1 50 14" stroke="url(#lg1)" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M 18 50 A 18 18 0 0 1 50 18" stroke="url(#lg1)" strokeWidth="2.5" strokeLinecap="round" opacity="0.7" />
      <path d="M 22 50 A 10 10 0 0 1 50 22" stroke="url(#lg1)" strokeWidth="2.5" strokeLinecap="round" opacity="0.45" />
      <circle cx="14" cy="50" r="3.5" fill="url(#lg1)" />
      <circle cx="50" cy="14" r="2" fill="#60a5fa" opacity="0.9" />
    </svg>
  )
}

export function AnimatedNumber({ value }: { value: number }) {
  const [display, setDisplay] = useState(0)
  useEffect(() => {
    const duration = 900
    const startTime = performance.now()
    const update = (currentNow: number) => {
      const progress = Math.min((currentNow - startTime) / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(Math.round(value * eased))
      if (progress < 1) requestAnimationFrame(update)
    }
    requestAnimationFrame(update)
  }, [value])
  return <>{display}</>
}

export function SourceLogo({ row }: { row: Row }) {
  return (
    <img
      src={getFaviconUrl(row)}
      alt=""
      width={14}
      height={14}
      style={{ borderRadius: 2, flexShrink: 0, display: 'block' }}
      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
    />
  )
}

export { hasAiSummary } from './utils-shared'
