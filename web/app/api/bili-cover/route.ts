import { NextRequest, NextResponse } from 'next/server'
import { createHash } from 'crypto'

export const runtime = 'nodejs'

const BV_RE = /^BV[A-Za-z0-9]{8,}$/

const BILI_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
  Referer: 'https://www.bilibili.com',
  Origin: 'https://www.bilibili.com',
}

// wbi 签名字符重排表（Bilibili 官方固定值）
const WBI_OE = [
  46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
  27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
  37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
  22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

let _wbiCache: { imgKey: string; subKey: string; fetchedAt: number } | null = null

async function getWbiKeys(): Promise<{ imgKey: string; subKey: string }> {
  const now = Date.now()
  // 每 24 小时刷新一次
  if (_wbiCache && now - _wbiCache.fetchedAt < 86400_000) {
    return { imgKey: _wbiCache.imgKey, subKey: _wbiCache.subKey }
  }
  const nav = await fetch('https://api.bilibili.com/x/web-interface/nav', {
    headers: BILI_HEADERS,
    cache: 'no-store',
  }).then((r) => r.json()) as { data?: { wbi_img?: { img_url?: string; sub_url?: string } } }

  const wbi = nav?.data?.wbi_img ?? {}
  const parseKey = (url = '') => (url.match(/\/([^/]+)\.\w+$/) ?? [])[1] ?? ''
  const imgKey = parseKey(wbi.img_url)
  const subKey = parseKey(wbi.sub_url)
  _wbiCache = { imgKey, subKey, fetchedAt: now }
  return { imgKey, subKey }
}

function getMixinKey(imgKey: string, subKey: string): string {
  const raw = imgKey + subKey
  return WBI_OE.filter((i) => i < raw.length).map((i) => raw[i]).join('').slice(0, 32)
}

async function buildWbiUrl(bvid: string): Promise<string> {
  const { imgKey, subKey } = await getWbiKeys()
  const mixin = getMixinKey(imgKey, subKey)
  const wts = Math.floor(Date.now() / 1000)
  const params = Object.entries({ bvid, wts }).sort(([a], [b]) => a.localeCompare(b))
  const SPECIAL = new Set([..."!'()*"])
  const rawQuery = params
    .map(([k, v]) => `${k}=${String(v).split('').filter((c) => !SPECIAL.has(c)).join('')}`)
    .join('&')
  const wRid = createHash('md5').update(rawQuery + mixin).digest('hex')
  return `https://api.bilibili.com/x/web-interface/view?${rawQuery}&w_rid=${wRid}`
}

function placeholderCoverResponse() {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540"><defs><linearGradient id="g" x1="0" x2="1" y1="0" y2="1"><stop offset="0%" stop-color="#0f172a"/><stop offset="100%" stop-color="#1e293b"/></linearGradient></defs><rect width="960" height="540" fill="url(#g)"/><circle cx="480" cy="240" r="72" fill="#334155"/><rect x="365" y="340" width="230" height="24" rx="12" fill="#475569"/><rect x="405" y="380" width="150" height="16" rx="8" fill="#334155"/></svg>`
  return new NextResponse(svg, {
    status: 200,
    headers: {
      'Content-Type': 'image/svg+xml; charset=utf-8',
      'Cache-Control': 'public, max-age=86400, s-maxage=86400',
    },
  })
}

export async function GET(req: NextRequest) {
  const bvid = req.nextUrl.searchParams.get('bvid') ?? ''

  if (!BV_RE.test(bvid)) {
    return placeholderCoverResponse()
  }

  try {
    // Step 1: 用 wbi 签名调 Bilibili API 拿封面 URL
    const apiUrl = await buildWbiUrl(bvid)
    const apiRes = await fetch(apiUrl, {
      headers: BILI_HEADERS,
      next: { revalidate: 3600 },
    })

    if (!apiRes.ok) {
      return placeholderCoverResponse()
    }

    const json = (await apiRes.json()) as { code?: number; data?: { pic?: string } }
    const pic = json?.data?.pic

    if (json?.code !== 0 || !pic || typeof pic !== 'string') {
      return placeholderCoverResponse()
    }

    const picUrl = pic.replace(/^http:/, 'https:')

    // Step 2: 代理图片字节，绕过 Bilibili 防盗链
    const imgRes = await fetch(picUrl, { headers: BILI_HEADERS })

    if (!imgRes.ok) {
      return placeholderCoverResponse()
    }

    const contentType = imgRes.headers.get('content-type') ?? 'image/jpeg'
    const body = await imgRes.arrayBuffer()

    return new NextResponse(body, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Cache-Control': 'public, max-age=3600, s-maxage=3600',
      },
    })
  } catch {
    return placeholderCoverResponse()
  }
}
