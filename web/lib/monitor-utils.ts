import type {
  MonitorSource,
  MonitorStatus,
  SourceRun,
  SourceSpec,
} from './monitor-types'
export const monitorLabels: Record<MonitorStatus, string> = {
  ok: '成功',
  failed: '失败',
  empty: '空结果',
  skipped: '跳过',
  never: '未运行',
  disabled: '停用',
  archived: '历史',
  unavailable: '未知',
}
export const monitorOrder: MonitorStatus[] = [
  'ok',
  'failed',
  'empty',
  'skipped',
  'never',
  'disabled',
  'archived',
  'unavailable',
]
export function errorCategory(message: string | null | undefined) {
  if (!message) return '未知错误'
  // Match response codes, not an HTTPS port (443) or numbers inside a URL.
  const code =
    message.match(/\b([45]\d\d)\s+(?:Client|Server)\s+Error\b/i) ||
    message.match(/\bHTTP(?:\/[\d.]+)?\s*[:=]?\s*([45]\d\d)\b/i) ||
    message.match(/\bstatus(?:_code)?\s*[:=]\s*([45]\d\d)\b/i) ||
    message.match(/^([45]\d\d)(?:\s|$)/)
  if (code) return `HTTP ${code[1]}`
  if (/timed?\s*out|timeout/i.test(message)) return '超时'
  if (/parse|SAX|syntax|invalid token/i.test(message)) return '解析错误'
  if (/connection|resolve|dns|ssl/i.test(message)) return '连接错误'
  return '其他错误'
}
export function compareSourceNames(
  a: Pick<MonitorSource, 'id' | 'name'>,
  b: Pick<MonitorSource, 'id' | 'name'>,
) {
  // Node and browsers can use different default locales. Keep SSR ordering stable.
  const left = a.name.toLowerCase(),
    right = b.name.toLowerCase()
  return left < right
    ? -1
    : left > right
      ? 1
      : a.id < b.id
        ? -1
        : a.id > b.id
          ? 1
          : 0
}
export function isStale(source: MonitorSource, now: number, hours: number) {
  return (
    !['disabled', 'historical'].includes(source.configuration) &&
    source.status !== 'unavailable' &&
    Boolean(source.lastRun) &&
    now - Date.parse(source.lastRun!) > hours * 3600000
  )
}
export function needsAttention(
  source: MonitorSource,
  now: number,
  hours: number,
) {
  if (
    ['disabled', 'historical'].includes(source.configuration) ||
    source.status === 'unavailable'
  )
    return false
  return (
    source.status === 'failed' ||
    source.status === 'never' ||
    source.emptyStreak >= 3 ||
    isStale(source, now, hours)
  )
}
export function attentionOrder(
  source: MonitorSource,
  now: number,
  hours: number,
) {
  if (
    source.configuration === 'disabled' ||
    source.configuration === 'historical'
  )
    return 6
  if (source.status === 'failed') return 0
  if (isStale(source, now, hours)) return 1
  if (source.emptyStreak >= 3) return 2
  if (source.status === 'never') return 3
  return 4
}
export function runStreak(runs: SourceRun[], status: SourceRun['status']) {
  let count = 0
  for (const run of runs) {
    if (run.status !== status) break
    count++
  }
  return count
}
export function successShare(runs: SourceRun[]) {
  const executed = runs.filter((r) => r.status !== 'skipped')
  return {
    successful: executed.filter(
      (r) => r.status === 'ok' || r.status === 'empty',
    ).length,
    total: executed.length,
  }
}
export function sourceDomain(address: string) {
  try {
    return new URL(address).hostname.replace(/^www\./, '')
  } catch {
    return address.startsWith('/')
      ? `RSSHub · ${address.split('/')[1]}`
      : '未记录域名'
  }
}
export function redactAddress(value: string) {
  try {
    const url = new URL(value)
    url.username = ''
    url.password = ''
    for (const key of [...url.searchParams.keys()])
      if (/token|key|secret|auth|password/i.test(key))
        url.searchParams.set(key, '[已隐藏]')
    return url.href
  } catch {
    return value
  }
}
export function redactError(value: string | null | undefined) {
  return value
    ? value.replace(/https?:\/\/[^\s'"<>]+/g, redactAddress).slice(0, 2000)
    : null
}
export function parseFeedRegistry(
  text: string,
  disabled: string,
): SourceSpec[] {
  const aliases: Record<string, string> = {
    twitter: 'twitter_user',
    twitter_user: 'twitter_user',
    bilibili: 'bilibili_user_video',
    bilibili_user_video: 'bilibili_user_video',
    werss: 'werss',
    default: 'default',
  }
  const off = new Set(
    disabled
      .split(',')
      .map((s) => aliases[s.trim().toLowerCase()])
      .filter(Boolean),
  )
  let section = 'auto'
  const entries: SourceSpec[] = []
  for (const line of text.split(/\r?\n/)) {
    const raw = line.trim()
    if (!raw || raw.startsWith('#')) continue
    const heading = raw.match(
      /^(?:\[(rsshub|direct|werss)\]|(rsshub|direct|werss):)$/i,
    )
    if (heading) {
      section = (heading[1] || heading[2]).toLowerCase()
      continue
    }
    const value = raw.replace(/^-?\d+\t\s*/, '')
    const split = value.indexOf(' # '),
      key = (split < 0 ? value : value.slice(0, split)).trim(),
      name = split < 0 ? '' : value.slice(split + 3).trim()
    if (!key) continue
    const bucket =
      section === 'werss'
        ? 'werss'
        : /^\/twitter\/user\//.test(key)
          ? 'twitter_user'
          : /^\/bilibili\/user\/video(?:-browser)?\//.test(key)
            ? 'bilibili_user_video'
            : 'default'
    entries.push({
      kind: 'tech',
      key,
      name,
      url: key,
      enabled: !off.has(bucket),
    })
  }
  return entries
}
/** Reads the single-line metadata subset used by policy_sources.toml, not selectors or policy content. */
export function parsePolicyRegistry(text: string): SourceSpec[] {
  return text
    .split(/^\s*\[\[sites\]\]\s*$/m)
    .slice(1)
    .flatMap((block) => {
      const fields: Record<string, string | boolean> = {}
      for (const line of block.split(/\r?\n/)) {
        const m = line.match(
          /^\s*(key|name|list_url|region|enabled)\s*=\s*("(?:[^"\\]|\\.)*"|'[^']*'|true|false)\s*(?:#.*)?$/,
        )
        if (!m) continue
        const value = m[2]
        fields[m[1]] =
          value === 'true'
            ? true
            : value === 'false'
              ? false
              : value.startsWith('"')
                ? JSON.parse(value)
                : value.slice(1, -1)
      }
      if (
        typeof fields.key !== 'string' ||
        typeof fields.name !== 'string' ||
        typeof fields.list_url !== 'string'
      )
        throw new Error('Unsupported policy registry metadata')
      return [
        {
          kind: 'policy' as const,
          key: fields.key,
          name: fields.name,
          url: fields.list_url,
          enabled: fields.enabled !== false,
          region: typeof fields.region === 'string' ? fields.region : undefined,
        },
      ]
    })
}
