'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Suspense, useEffect, useState, type ReactNode } from 'react'
import SearchBar from './SearchBar'
import {
  Home,
  Radio,
  Files,
  Layers3,
  ChartNoAxesCombined,
  Activity,
  Rss,
  Bookmark,
  Menu,
  X,
  ArrowUpRight,
} from 'lucide-react'
const links = [
  { href: '/', label: '总览', icon: Home },
  { href: '/signals', label: '技术信号', icon: Radio },
  { href: '/policies', label: '政策观察', icon: Files },
  { href: '/topics', label: '专题对读', icon: Layers3 },
  { href: '/predictions', label: '预测与复盘', icon: ChartNoAxesCombined },
  { href: '/monitor', label: '运行监控', icon: Activity },
]
export default function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  const [menu, setMenu] = useState(false)
  useEffect(() => {
    setMenu(false)
  }, [pathname])
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setMenu(false)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])
  return (
    <div
      className={`journal-shell ${pathname === '/signals' || pathname === '/policies' ? 'reader-shell' : ''}`}
    >
      <a href="#content" className="skip-link">
        跳到主要内容
      </a>
      {menu && (
        <button
          className="nav-backdrop"
          aria-label="关闭导航"
          onClick={() => setMenu(false)}
        />
      )}
      <aside className={`journal-sidebar ${menu ? 'is-open' : ''}`}>
        <Link href="/" className="brand">
          <span className="brand-mark">
            <Rss size={23} />
          </span>
          <span>
            RSS2Cubox<small>让重要的信息，被更好地阅读</small>
          </span>
        </Link>
        <nav aria-label="主导航">
          {links.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              aria-current={
                (href === '/' ? pathname === '/' : pathname.startsWith(href))
                  ? 'page'
                  : undefined
              }
            >
              <Icon size={19} strokeWidth={1.65} />
              {label}
            </Link>
          ))}
        </nav>
        <div className="nav-secondary">
          <Link
            href="/saved"
            aria-current={pathname === '/saved' ? 'page' : undefined}
          >
            <Bookmark size={18} />
            我的收藏
          </Link>
        </div>
        <div className="sidebar-foot">
          <span className="little-flower">✳</span>
          <p>
            在信息的缝隙里，
            <br />
            看见变化的回响。
          </p>
          <Link href="/monitor">
            数据与运行状态 <ArrowUpRight size={13} />
          </Link>
        </div>
      </aside>
      <div className="journal-workspace">
        <header className="journal-topbar">
          <button
            className="icon-button mobile-menu"
            aria-label={menu ? '关闭导航' : '打开导航'}
            aria-expanded={menu}
            onClick={() => setMenu(!menu)}
          >
            {menu ? <X size={20} /> : <Menu size={20} />}
          </button>
          <Suspense
            fallback={
              <div
                className="global-search search-placeholder"
                aria-label="搜索加载中"
              />
            }
          >
            <SearchBar />
          </Suspense>
          <span className="topbar-note">技术与政策的日常阅读</span>
          <Link className="icon-button" href="/saved" aria-label="打开我的收藏">
            <Bookmark size={18} />
          </Link>
          <span className="identity-mark" aria-hidden="true">
            R
          </span>
        </header>
        <main id="content" className="journal-content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  )
}
