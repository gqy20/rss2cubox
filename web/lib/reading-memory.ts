/** Per-tab UI memory, bounded and independent of the data/cache query keys. */
const values = new Map<string, unknown>()
const PREFIX = 'rss-reading:'
export function readMemory<T>(key: string, fallback: T): T {
  if (values.has(key)) return values.get(key) as T
  try {
    const raw = sessionStorage.getItem(PREFIX + key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}
export function writeMemory(key: string, value: unknown) {
  values.delete(key)
  values.set(key, value)
  while (values.size > 40) {
    const oldest = values.keys().next().value!
    values.delete(oldest)
    try {
      sessionStorage.removeItem(PREFIX + oldest)
    } catch {}
  }
  try {
    sessionStorage.setItem(PREFIX + key, JSON.stringify(value))
  } catch {}
}
export function clearMemory(key: string) {
  values.delete(key)
  try {
    sessionStorage.removeItem(PREFIX + key)
  } catch {}
}
