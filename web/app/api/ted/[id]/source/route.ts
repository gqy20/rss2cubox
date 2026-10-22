import { NextRequest, NextResponse } from 'next/server'
import { readTedSourceDetail } from '../../../../../lib/ted-source-store'
import { tedError, tedHeaders } from '../../../../../lib/ted-api'
export const dynamic = 'force-dynamic'

export async function GET(request: NextRequest, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params
  const sourceId = request.nextUrl.searchParams.get('id') || ''
  if (!sourceId || sourceId.length > 255)
    return NextResponse.json({ error: '请提供有效的资料编号。' }, { status: 400, headers: tedHeaders })
  try {
    const data = await readTedSourceDetail(id, sourceId)
    return NextResponse.json(data ? { data } : { error: '未找到这条资料。' }, { status: data ? 200 : 404, headers: tedHeaders })
  } catch (error) { return tedError(error) }
}
