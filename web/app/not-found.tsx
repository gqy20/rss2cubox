import Link from 'next/link'
export default function NotFound() {
  return (
    <section className="surface error-panel">
      <h1>没有找到这份内容</h1>
      <p>记录可能已移除，或链接不完整。</p>
      <Link className="primary-button" href="/">
        回到简报
      </Link>
    </section>
  )
}
