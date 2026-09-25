'use client'
// Catches errors thrown by the root layout itself, where error.tsx cannot.
export default function GlobalError({ reset }: { reset: () => void }) {
  return (
    <html lang="zh-CN">
      <body>
        <main
          style={{
            fontFamily: 'system-ui, sans-serif',
            maxWidth: 420,
            margin: '18vh auto',
            padding: '0 20px',
            color: '#33302b',
          }}
        >
          <h1 style={{ fontSize: 21 }}>页面暂时无法加载</h1>
          <p style={{ lineHeight: 1.8, color: '#5c6250' }}>
            出现了未预期的问题。请重试，或稍后直接刷新页面。
          </p>
          <button
            onClick={reset}
            style={{
              border: '1px solid #d8d2c8',
              background: '#fff',
              borderRadius: 999,
              padding: '9px 22px',
              cursor: 'pointer',
            }}
          >
            重新加载
          </button>
        </main>
      </body>
    </html>
  )
}
