/**
 * 信源建议（source_suggestions）：外部用户提交候选信源 → 自动体检 →
 * 人工审核（accepted 后由维护者写入 feeds.txt / policy_sources.toml）。
 *
 * 体检只做"这个 URL 值不值得人工适配"的判断，不代替适配本身：
 * - RSS：解析活性 + 最近条目的 AI 关键词密度（即时信噪比预估）
 * - 政策 HTML：返回内容量级 + 列表锚密度（JS 壳站会暴露出来）
 */
import { queryJournal } from './journal-store'

const DDL = `
CREATE TABLE IF NOT EXISTS source_suggestions (
    id           SERIAL PRIMARY KEY,
    url          TEXT NOT NULL,
    name         TEXT NOT NULL DEFAULT '',
    kind         TEXT NOT NULL CHECK (kind IN ('tech','policy')),
    note         TEXT DEFAULT '',
    submitted_by TEXT DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','accepted','rejected')),
    health       JSONB DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_source_suggestions_url ON source_suggestions(url);
`

export type Suggestion = {
  id: number
  url: string
  name: string
  kind: 'tech' | 'policy'
  note: string
  submitted_by: string
  status: string
  health: {
    verdict?: 'rss_ok' | 'rss_weak' | 'html_candidate' | 'js_shell' | 'unreachable'
    detail?: string
    items?: number
    ai_keyword_ratio?: number
    sample_titles?: string[]
  }
  created_at: string
}

export async function ensureSuggestionTable() {
  await queryJournal(DDL)
}

export async function listSuggestions(): Promise<Suggestion[]> {
  return queryJournal<Suggestion>(
    'SELECT id,url,name,kind,note,submitted_by,status,health,created_at FROM source_suggestions ORDER BY created_at DESC',
  )
}

export async function createSuggestion(input: {
  url: string
  name?: string
  kind?: string
  note?: string
  submitted_by?: string
}): Promise<Suggestion> {
  await ensureSuggestionTable()
  const kind = input.kind === 'policy' ? 'policy' : 'tech'
  const health = await inspectSource(input.url, kind)
  const [row] = await queryJournal<Suggestion>(
    `INSERT INTO source_suggestions (url,name,kind,note,submitted_by,health)
     VALUES ($1,$2,$3,$4,$5,$6)
     ON CONFLICT (url) DO UPDATE SET
       name = EXCLUDED.name, note = EXCLUDED.note,
       submitted_by = EXCLUDED.submitted_by, health = EXCLUDED.health,
       updated_at = now()
     RETURNING id,url,name,kind,note,submitted_by,status,health,created_at`,
    [
      input.url,
      (input.name || '').slice(0, 100),
      kind,
      (input.note || '').slice(0, 500),
      (input.submitted_by || '').slice(0, 100),
      JSON.stringify(health),
    ],
  )
  return row
}

// ── 体检 ───────────────────────────────────────────────────────

const AI_KEYWORDS = [
  'ai', '人工智能', 'llm', '大模型', '模型', '智能体', 'agent', 'gpt',
  '机器学习', '深度学习', 'neural', 'openai', 'anthropic', '推理',
]
const POLICY_KEYWORDS = ['通知', '办法', '意见', '规划', '条例', '公告', '政策', '方案']

async function fetchWithTimeout(url: string, ms = 10_000) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), ms)
  try {
    return await fetch(url, {
      signal: controller.signal,
      headers: { 'user-agent': 'Mozilla/5.0 (compatible; rss2cubox-suggest/1.0)' },
      redirect: 'follow',
    })
  } finally {
    clearTimeout(timer)
  }
}

export async function inspectSource(url: string, kind: 'tech' | 'policy') {
  let body: string
  try {
    const res = await fetchWithTimeout(url)
    if (!res.ok) return { verdict: 'unreachable', detail: `HTTP ${res.status}` } as const
    body = (await res.text()).slice(0, 400_000)
  } catch (e) {
    return {
      verdict: 'unreachable',
      detail: e instanceof Error ? e.name : 'fetch_failed',
    } as const
  }

  const looksRss = /<(rss|feed)[\s>]/i.test(body) || /<\?xml[^>]*\?>\s*<rss/i.test(body)
  if (looksRss) {
    const titles = [...body.matchAll(/<title[^>]*>([\s\S]{4,200}?)<\/title>/gi)]
      .map((m) => m[1].replace(/<!\[CDATA\[|\]\]>/g, '').replace(/\s+/g, ' ').trim())
      // 第一条 <title> 是频道名，跳过
      .slice(1, 11)
      .filter((t) => !/^https?:/.test(t))
    const items = (body.match(/<(item|entry)[\s>]/gi) || []).length
    const keywords = kind === 'policy' ? POLICY_KEYWORDS : AI_KEYWORDS
    const hit = titles.filter((t) =>
      keywords.some((k) => t.toLowerCase().includes(k.toLowerCase())),
    ).length
    const ratio = titles.length ? Number((hit / titles.length).toFixed(2)) : 0
    return {
      verdict: items >= 5 ? 'rss_ok' : 'rss_weak',
      detail: items >= 5 ? 'RSS 可直接解析' : `RSS 条目过少（${items}）`,
      items,
      ai_keyword_ratio: ratio,
      sample_titles: titles.slice(0, 5),
    } as const
  }

  // HTML：判断是服务端渲染的列表页还是 JS 空壳
  const anchors = (body.match(/<a\s[^>]*href=/gi) || []).length
  const chinese = (body.match(/[一-龥]/g) || []).length
  if (body.length < 2_000 || anchors < 10) {
    return {
      verdict: 'js_shell',
      detail: `疑似 JS 空壳（${body.length}B / ${anchors} 链接），需 playwright 且要人工适配选择器`,
    } as const
  }
  return {
    verdict: 'html_candidate',
    detail: `服务端渲染（${Math.round(body.length / 1024)}KB / ${anchors} 链接 / 中文${chinese}字符），需人工适配 CSS 选择器后接入`,
  } as const
}
