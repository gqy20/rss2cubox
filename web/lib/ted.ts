/** Shared report contract. Dates in the editor are inclusive Shanghai calendar dates. */
export type TedSource = {
  analysis?: TedSourceAnalysis | null
  id: string
  kind: 'article' | 'policy' | 'external'
  title: string
  url: string
  publisher: string
  published_at: string | null
  date_basis: 'published' | 'collected' | 'unknown'
  summary: string
  reason: string
  cluster_id?: number | null
  cluster_label?: string | null
}
export type TedSourceAnalysis = {
  kind: 'article' | 'policy'
  importance_score: number | null
  ai_relevance: number | null
  reason: string
  hidden_signal: string
  actionable: string
  prediction: string
  summary: string
  source_quote: string
  tags: string[]
}
export type TedSourceDetail = {
  source: Pick<TedSource, 'id' | 'title' | 'url' | 'publisher' | 'reason'>
  analysis: TedSourceAnalysis | null
  record_id: string | null
}
export type TedImage = { url: string; alt: string }
export type TedTopic = {
  id: string
  title: string
  claim: string
  body: string
  uncertainty: string
  watch: string
  host_notes: string
  image: TedImage | null
  sources: TedSource[]
}
export type TedCoverage = {
  articles: number
  policies: number
  analyzed: number
  sources: number
  latest_article: string | null
  latest_policy: string | null
}
export type TedReport = {
  edition_date?: string
  title: string
  intro: string
  tags: string[]
  start_date: string
  end_date: string
  cutoff_at: string
  coverage: TedCoverage
  topics: TedTopic[]
  next_watch: string
  cover: TedImage | null
  live_at: string
  live_url: string
  replay_url: string
  preparation: 'assembled' | 'edited'
  generation?: { method: 'agent'; generated_at: string }
}
export type TedIssue = {
  id: string
  issue_number: number
  version: number
  published_version: number | null
  published_at: string | null
  updated_at: string
  created_at: string
  report: TedReport
}
export type TedMaterials = {
  start_date: string
  end_date: string
  cutoff_at: string
  coverage: TedCoverage
  materials: TedSource[]
  limit: number
}
export class TedValidationError extends Error {}

export function httpUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return (
      ['http:', 'https:'].includes(url.protocol) &&
      !url.username &&
      !url.password
    )
  } catch {
    return false
  }
}

export function validateWindow(start: string, end: string) {
  for (const value of [start, end]) {
    if (
      !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
      !Number.isFinite(Date.parse(value)) ||
      new Date(value).toISOString().slice(0, 10) !== value
    )
      throw new TedValidationError('请选择有效的覆盖日期。')
  }
  const days = (Date.parse(end) - Date.parse(start)) / 86400000 + 1
  if (days < 1 || days > 31)
    throw new TedValidationError(
      '覆盖区间应为 1–31 天，结束日期不能早于开始日期。',
    )
  // Explicit offsets avoid depending on the database session timezone.
  return {
    start: `${start}T00:00:00+08:00`,
    end: new Date(Date.parse(`${end}T00:00:00+08:00`) + 86400000).toISOString(),
  }
}

export function defaultWindow(now = new Date()) {
  const end = new Date(now.getTime() - 86400000).toLocaleDateString('en-CA', {
    timeZone: 'Asia/Shanghai',
  })
  return {
    start: new Date(Date.parse(end) - 6 * 86400000).toISOString().slice(0, 10),
    end,
  }
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new TedValidationError('报告内容格式不正确。')
  return value as Record<string, unknown>
}
function text(value: unknown, max = 20000): string {
  if (typeof value !== 'string' || value.length > max)
    throw new TedValidationError(`文字字段格式不正确或超过 ${max} 字。`)
  return value.trim()
}
function image(value: unknown): TedImage | null {
  if (value == null) return null
  const row = record(value),
    url = text(row.url, 2000),
    alt = text(row.alt, 300)
  if (!url) return null
  if (!httpUrl(url) || !alt)
    throw new TedValidationError('图片需要有效的 http(s) 地址和图片说明。')
  return { url, alt }
}
function date(value: unknown): string | null {
  if (value == null || value === '') return null
  const input = text(value, 100)
  if (!Number.isFinite(Date.parse(input)))
    throw new TedValidationError('时间格式不正确。')
  return new Date(input).toISOString()
}

export function parseSourceAnalysis(value: unknown): TedSourceAnalysis | null {
  if (value == null) return null
  const row = record(value)
  if (row.kind !== 'article' && row.kind !== 'policy') throw new TedValidationError('分析类型不正确。')
  const score = (key: string) => {
    const value = row[key]
    if (value == null) return null
    if (typeof value !== 'number' || !Number.isInteger(value) || value < 1 || value > 5)
      throw new TedValidationError('分析评分不正确。')
    return value
  }
  const tags = row.tags == null ? [] : row.tags
  if (!Array.isArray(tags) || tags.length > 30) throw new TedValidationError('分析标签格式不正确。')
  return {
    kind: row.kind, importance_score: score('importance_score'), ai_relevance: score('ai_relevance'),
    reason: text(row.reason ?? ''), hidden_signal: text(row.hidden_signal ?? ''),
    actionable: text(row.actionable ?? ''), prediction: text(row.prediction ?? ''),
    summary: text(row.summary ?? ''), source_quote: text(row.source_quote ?? ''),
    tags: tags.map((tag) => text(tag, 200)),
  }
}

export function parseReport(value: unknown, publishing = false): TedReport {
  const row = record(value)
  const start_date = text(row.start_date, 10),
    end_date = text(row.end_date, 10)
  validateWindow(start_date, end_date)
  if (!Array.isArray(row.topics) || row.topics.length > 20)
    throw new TedValidationError('每期最多保留 20 个议题。')
  const topics: TedTopic[] = row.topics.map((input) => {
    const topic = record(input)
    const id = text(topic.id, 80)
    if (!/^[a-zA-Z0-9_-]{1,80}$/.test(id))
      throw new TedValidationError('议题标识不正确。')
    if (!Array.isArray(topic.sources) || topic.sources.length > 30)
      throw new TedValidationError('每个议题最多引用 30 条资料。')
    const sources: TedSource[] = topic.sources.map((inputSource) => {
      const source = record(inputSource)
      const kind = source.kind
      if (!['article', 'policy', 'external'].includes(String(kind)))
        throw new TedValidationError('来源类型不正确。')
      const url = text(source.url, 2000)
      if (!httpUrl(url))
        throw new TedValidationError('引用链接必须是有效的 http(s) 原文地址。')
      const basis = source.date_basis
      if (!['published', 'collected', 'unknown'].includes(String(basis)))
        throw new TedValidationError('来源日期口径不正确。')
      const result: TedSource = {
        analysis: parseSourceAnalysis(source.analysis),
        id: text(source.id, 255),
        kind: kind as TedSource['kind'],
        title: text(source.title, 1000),
        url,
        publisher: text(source.publisher, 500),
        published_at: date(source.published_at),
        date_basis: basis as TedSource['date_basis'],
        summary: text(source.summary),
        reason: text(source.reason, 2000),
      }
      if (!result.id || !result.title)
        throw new TedValidationError('引用资料需要标题和标识。')
      if (publishing && !result.reason)
        throw new TedValidationError('请为每条引用补充“支持了哪一点”。')
      return result
    })
    if (new Set(sources.map((s) => sourceKey(s))).size !== sources.length)
      throw new TedValidationError('同一议题中有重复引用，请合并。')
    const result: TedTopic = {
      id,
      title: text(topic.title, 500),
      claim: text(topic.claim, 4000),
      body: text(topic.body),
      uncertainty: text(topic.uncertainty, 4000),
      watch: text(topic.watch, 4000),
      host_notes: text(topic.host_notes),
      image: image(topic.image),
      sources,
    }
    if (publishing && (!result.title || !result.claim || !sources.length))
      throw new TedValidationError(
        '每个议题需要标题、核心判断和至少一条原文依据，才能发布。',
      )
    // Citation numbers are scoped to one topic, so reordering topics stays safe.
    for (const field of [
      result.claim,
      result.body,
      result.uncertainty,
      result.watch,
    ]) {
      for (const match of field.matchAll(/\[(\d+)\](?!\()/g)) {
        if (Number(match[1]) < 1 || Number(match[1]) > sources.length)
          throw new TedValidationError(
            `议题“${result.title || '未命名'}”引用了不存在的资料 [${match[1]}]。`,
          )
      }
    }
    return result
  })
  if (new Set(topics.map((t) => t.id)).size !== topics.length)
    throw new TedValidationError('议题标识不能重复。')
  if (!Array.isArray(row.tags) || row.tags.length > 10)
    throw new TedValidationError('最多设置 10 个主题标签。')
  const coverage = record(row.coverage)
  const count = (key: string) => {
    const n = coverage[key]
    if (typeof n !== 'number' || !Number.isSafeInteger(n) || n < 0)
      throw new TedValidationError('覆盖统计格式不正确。')
    return n
  }
  const result: TedReport = {
    title: text(row.title, 300),
    intro: text(row.intro, 5000),
    tags: row.tags.map((tag) => text(tag, 80)).filter(Boolean),
    start_date,
    end_date,
    cutoff_at: date(row.cutoff_at) || '',
    coverage: {
      articles: count('articles'),
      policies: count('policies'),
      analyzed: count('analyzed'),
      sources: count('sources'),
      latest_article: date(coverage.latest_article),
      latest_policy: date(coverage.latest_policy),
    },
    topics,
    next_watch: text(row.next_watch),
    cover: image(row.cover),
    live_at: date(row.live_at) || '',
    live_url: text(row.live_url, 2000),
    replay_url: text(row.replay_url, 2000),
    preparation: row.preparation === 'assembled' ? 'assembled' : 'edited',
  }
  if (row.generation != null) {
    const generation = record(row.generation)
    const generated_at = date(generation.generated_at)
    if (generation.method !== 'agent' || !generated_at)
      throw new TedValidationError('生成记录格式不正确。')
    result.generation = { method: 'agent', generated_at }
  }
  if (row.edition_date != null && row.edition_date !== '') {
    const edition = text(row.edition_date, 10)
    validateWindow(edition, edition)
    result.edition_date = edition
  }
  if (!result.cutoff_at) throw new TedValidationError('缺少数据截止时间。')
  for (const url of [result.live_url, result.replay_url])
    if (url && !httpUrl(url))
      throw new TedValidationError('直播和回放需要有效的 http(s) 链接。')
  if (publishing && (!result.title || !result.intro || !topics.length))
    throw new TedValidationError('请填写本期标题、导读，并至少选入一个议题。')
  return result
}

export function sourceKey(source: Pick<TedSource, 'url'>) {
  try {
    const url = new URL(source.url)
    url.hash = ''
    for (const key of [...url.searchParams.keys()])
      if (/^utm_|^(fbclid|gclid)$/i.test(key)) url.searchParams.delete(key)
    url.searchParams.sort()
    return url.toString()
  } catch {
    return source.url
  }
}

export function removeTopicSource(topic: TedTopic, index: number): TedTopic {
  const fields = [topic.claim, topic.body, topic.uncertainty, topic.watch]
  if (
    fields.some((field) =>
      [...field.matchAll(/\[(\d+)\](?!\()/g)].some(
        (match) => Number(match[1]) === index + 1,
      ),
    )
  )
    throw new TedValidationError(
      `请先移除正文中的引用 [${index + 1}]，再移除这条资料。`,
    )
  const renumber = (field: string) =>
    field.replace(/\[(\d+)\](?!\()/g, (match, n) =>
      Number(n) > index + 1 ? `[${Number(n) - 1}]` : match,
    )
  return {
    ...topic,
    claim: renumber(topic.claim),
    body: renumber(topic.body),
    uncertainty: renumber(topic.uncertainty),
    watch: renumber(topic.watch),
    sources: topic.sources.filter((_, i) => i !== index),
  }
}

export function publicReport(report: TedReport): TedReport {
  return {
    ...report,
    topics: report.topics.map((topic) => ({ ...topic, host_notes: '' })),
  }
}

export function groupMaterials(materials: TedSource[]): TedTopic[] {
  const groups = new Map<string, TedTopic>()
  const seen = new Set<string>()
  for (const source of materials) {
    if (!httpUrl(source.url) || seen.has(sourceKey(source))) continue
    seen.add(sourceKey(source))
    const key =
      source.kind === 'article' && source.cluster_id
        ? `cluster-${source.cluster_id}`
        : `${source.kind}-${source.id}`
    let topic = groups.get(key)
    if (!topic) {
      topic = {
        id: `topic-${groups.size + 1}`,
        title: source.cluster_label || source.title,
        claim: '',
        body: '',
        uncertainty: '',
        watch: '',
        host_notes: '',
        image: null,
        sources: [],
      }
      groups.set(key, topic)
    }
    if (topic.sources.length < 12) topic.sources.push({ ...source, reason: '' })
  }
  return [...groups.values()].sort(
    (a, b) => b.sources.length - a.sources.length,
  )
}

export function assembleReport(packet: TedMaterials): TedReport {
  const candidates = groupMaterials(packet.materials)
  const tech = candidates
    .filter((t) => t.sources[0]?.kind === 'article')
    .slice(0, 4)
  const policy = candidates
    .filter((t) => t.sources[0]?.kind === 'policy')
    .slice(0, 1)
  return {
    title: '',
    intro: '',
    tags: [],
    start_date: packet.start_date,
    end_date: packet.end_date,
    cutoff_at: packet.cutoff_at,
    coverage: packet.coverage,
    topics: [...tech, ...policy],
    next_watch: '',
    cover: null,
    live_at: '',
    live_url: '',
    replay_url: '',
    preparation: 'assembled',
  }
}

export function tedDate(value: string | null | undefined, withTime = false) {
  if (!value || !Number.isFinite(Date.parse(value))) return '未明确'
  return new Date(value).toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    ...(withTime ? ({ hour: '2-digit', minute: '2-digit' } as const) : {}),
  })
}

export const TED_TITLE = '他山青年 TED 灵感共创队'

export function tedEditionDate(
  report: Pick<TedReport, 'edition_date' | 'live_at' | 'end_date'>,
) {
  if (report.edition_date) return report.edition_date
  if (report.live_at && Number.isFinite(Date.parse(report.live_at)))
    return new Date(report.live_at).toLocaleDateString('en-CA', {
      timeZone: 'Asia/Shanghai',
    })
  const end = Date.parse(report.end_date)
  return Number.isFinite(end)
    ? new Date(end + 86400000).toISOString().slice(0, 10)
    : ''
}

export function tedEditionLabel(
  report: Pick<TedReport, 'edition_date' | 'live_at' | 'end_date'>,
) {
  const date = tedEditionDate(report)
  return date ? `${date.slice(5, 7)}.${date.slice(8, 10)} 期` : '日期待定'
}

export function isTedId(value: string) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
    value,
  )
}
