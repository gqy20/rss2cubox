// In-process TTL memoization for low-frequency server reads. The app runs as
// a single long-lived Node process, so a module-level cache is enough —
// failed calls are evicted immediately so the next request retries.
export function memoize<T>(fn: () => Promise<T>, ms: number): () => Promise<T> {
  let at = 0,
    value: Promise<T> | null = null
  return () => {
    if (value && Date.now() - at < ms) return value
    at = Date.now()
    value = fn().catch((error) => {
      value = null
      throw error
    })
    return value
  }
}
export function memoizeArg<A, T>(
  fn: (arg: A) => Promise<T>,
  ms: number,
): (arg: A) => Promise<T> {
  const entries = new Map<string, { at: number; value: Promise<T> }>()
  return (arg) => {
    const key = JSON.stringify(arg),
      hit = entries.get(key)
    if (hit && Date.now() - hit.at < ms) return hit.value
    const value = fn(arg).catch((error) => {
      entries.delete(key)
      throw error
    })
    entries.set(key, { at: Date.now(), value })
    if (entries.size > 50) entries.delete(entries.keys().next().value!)
    return value
  }
}
