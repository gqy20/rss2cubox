export default function Loading() {
  return (
    <div aria-label="正在加载内容" role="status">
      <div className="loading-skeleton loading-title" />
      {[1, 2, 3].map((i) => (
        <div key={i} className="loading-skeleton" />
      ))}
    </div>
  )
}
