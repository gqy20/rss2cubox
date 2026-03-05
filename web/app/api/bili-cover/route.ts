import { NextRequest, NextResponse } from 'next/server'

export const runtime = 'nodejs'

const BV_RE = /^BV[A-Za-z0-9]{8,}$/

export async function GET(req: NextRequest) {
  const bvid = req.nextUrl.searchParams.get('bvid') ?? ''

  if (!BV_RE.test(bvid)) {
    return new NextResponse(null, { status: 400 })
  }

  try {
    const res = await fetch(`https://api.bilibili.com/x/web-interface/view?bvid=${bvid}`, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        Referer: 'https://www.bilibili.com',
        Origin: 'https://www.bilibili.com',
      },
      next: { revalidate: 3600 },
    })

    if (!res.ok) {
      return new NextResponse(null, { status: 502 })
    }

    const json = (await res.json()) as { data?: { pic?: string } }
    const pic = json?.data?.pic

    if (!pic || typeof pic !== 'string') {
      return new NextResponse(null, { status: 404 })
    }

    // Use https for the redirect target
    const picUrl = pic.replace(/^http:/, 'https:')
    return NextResponse.redirect(picUrl, { status: 302 })
  } catch {
    return new NextResponse(null, { status: 502 })
  }
}
