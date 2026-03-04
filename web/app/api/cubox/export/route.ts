import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { buildCuboxApiUrl, CUBOX_KEY_COOKIE, decryptCuboxKey } from '../../../../lib/cuboxCookie'

export const runtime = 'nodejs'

type ExportItem = {
  url?: string
  title?: string
  tags?: string[]
}

type ExportBody = {
  items?: ExportItem[]
  folder?: string
}

export async function POST(req: Request) {
  const jar = await cookies()
  const cookieValue = jar.get(CUBOX_KEY_COOKIE)?.value
  if (!cookieValue) {
    return NextResponse.json({ error: 'Cubox key is not configured' }, { status: 401 })
  }

  let cuboxRawKey = ''
  try {
    cuboxRawKey = decryptCuboxKey(cookieValue)
  } catch {
    return NextResponse.json({ error: 'Cubox key is invalid, please reset it' }, { status: 401 })
  }

  let body: ExportBody
  try {
    body = (await req.json()) as ExportBody
  } catch {
    return NextResponse.json({ error: 'Invalid JSON body' }, { status: 400 })
  }

  const items = Array.isArray(body.items) ? body.items : []
  if (!items.length) return NextResponse.json({ error: 'No export items' }, { status: 400 })

  const folder = String(body.folder || 'RSS Inbox').trim()
  const apiUrl = buildCuboxApiUrl(cuboxRawKey)

  const validItems = items
    .map((item) => ({
      url: String(item.url || '').trim(),
      title: String(item.title || '').trim(),
      tags: Array.isArray(item.tags) ? item.tags.map((t) => String(t).trim()).filter(Boolean).slice(0, 8) : [],
    }))
    .filter((item) => item.url)

  const seen = new Set<string>()
  const deduped = validItems.filter((item) => {
    if (seen.has(item.url)) return false
    seen.add(item.url)
    return true
  })

  const failures: Array<{ url: string; error: string }> = []
  let success = 0

  for (const item of deduped.slice(0, 100)) {
    const payload: Record<string, unknown> = { type: 'url', content: item.url, folder }
    if (item.title) payload.title = item.title
    if (item.tags.length > 0) payload.tags = item.tags

    try {
      const res = await fetch(apiUrl, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        const text = await res.text()
        failures.push({ url: item.url, error: `HTTP ${res.status}: ${text.slice(0, 180)}` })
      } else {
        success += 1
      }
    } catch (err) {
      failures.push({ url: item.url, error: err instanceof Error ? err.message : 'Network error' })
    }
  }

  return NextResponse.json({
    ok: failures.length === 0,
    requested: items.length,
    attempted: deduped.length,
    success,
    failed: failures.length,
    failures: failures.slice(0, 10),
  })
}
