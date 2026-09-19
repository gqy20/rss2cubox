'use client'
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <section className="surface error-panel">
      <h2>内容暂时无法加载</h2>
      <p>数据连接可能暂时不可用。请稍后重试，或到其他页面继续阅读。</p>
      <button className="primary-button" onClick={reset}>
        重新加载
      </button>
    </section>
  )
}
