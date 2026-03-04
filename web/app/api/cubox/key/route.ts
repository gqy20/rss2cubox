import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import { buildCuboxApiUrl, CUBOX_KEY_COOKIE, decryptCuboxKey, encryptCuboxKey } from '../../../../lib/cuboxCookie'

export const runtime = 'nodejs'

type Body = {
  key?: string
}

export async function GET() {
  const jar = await cookies()
  const raw = jar.get(CUBOX_KEY_COOKIE)?.value
  if (!raw) return NextResponse.json({ configured: false })

  try {
    decryptCuboxKey(raw)
    return NextResponse.json({ configured: true })
  } catch {
    return NextResponse.json({ configured: false })
  }
}

export async function POST(req: Request) {
  let body: Body
  try {
    body = (await req.json()) as Body
  } catch {
    return NextResponse.json({ error: 'Invalid JSON body' }, { status: 400 })
  }

  const key = String(body.key || '').trim()
  if (!key) return NextResponse.json({ error: 'Cubox key is required' }, { status: 400 })

  try {
    buildCuboxApiUrl(key)
  } catch (err) {
    return NextResponse.json({ error: err instanceof Error ? err.message : 'Invalid key' }, { status: 400 })
  }

  try {
    const encrypted = encryptCuboxKey(key)
    const res = NextResponse.json({ ok: true })
    res.cookies.set({
      name: CUBOX_KEY_COOKIE,
      value: encrypted,
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      path: '/',
      maxAge: 60 * 60 * 24 * 7,
    })
    return res
  } catch (err) {
    return NextResponse.json(
      {
        error:
          err instanceof Error && err.message.includes('CUBOX_COOKIE_SECRET')
            ? '服务端未配置 CUBOX_COOKIE_SECRET，无法保存 Cubox Key'
            : err instanceof Error
              ? err.message
              : 'Failed to save cubox key',
      },
      { status: 500 }
    )
  }
}

export async function DELETE() {
  const res = NextResponse.json({ ok: true })
  res.cookies.set({
    name: CUBOX_KEY_COOKIE,
    value: '',
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/',
    maxAge: 0,
  })
  return res
}
