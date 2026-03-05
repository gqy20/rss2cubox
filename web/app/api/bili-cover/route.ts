import { NextRequest, NextResponse } from 'next/server'

export const runtime = 'nodejs'

const BV_RE = /^BV[A-Za-z0-9]{8,}$/

const BILI_HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
  Referer: 'https://www.bilibili.com',
  Origin: 'https://www.bilibili.com',
}

export async function GET(req: NextRequest) {
  const bvid = req.nextUrl.searchParams.get('bvid') ?? ''

  if (!BV_RE.test(bvid)) {
    return new NextResponse(null, { status: 400 })
  }

  try {
    // Step 1: resolve cover URL from Bilibili API (cached 1h)
    const apiRes = await fetch(`https://api.bilibili.com/x/web-interface/view?bvid=${bvid}`, {
      headers: BILI_HEADERS,
      next: { revalidate: 3600 },
    })

    if (!apiRes.ok) {
      return new NextResponse(null, { status: 502 })
    }

    const json = (await apiRes.json()) as { data?: { pic?: string } }
    const pic = json?.data?.pic

    if (!pic || typeof pic !== 'string') {
      return new NextResponse(null, { status: 404 })
    }

    const picUrl = pic.replace(/^http:/, 'https:')

    // Step 2: proxy the image bytes through our server so browser avoids hotlink checks
    const imgRes = await fetch(picUrl, { headers: BILI_HEADERS })

    if (!imgRes.ok) {
      return new NextResponse(null, { status: 502 })
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
    return new NextResponse(null, { status: 502 })
  }
}
