import { NextRequest, NextResponse } from 'next/server'
import { readTedMaterials } from '../../../../lib/ted-store'
import { tedError, tedHeaders } from '../../../../lib/ted-api'
export const dynamic = 'force-dynamic'
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl
    const cutoff = searchParams.get('cutoff') || new Date().toISOString()
    if (!Number.isFinite(Date.parse(cutoff)) || Date.parse(cutoff) > Date.now())
      return NextResponse.json(
        { error: '数据截止时间无效。' },
        { status: 400, headers: tedHeaders },
      )
    return NextResponse.json(
      {
        data: await readTedMaterials(
          searchParams.get('start') || '',
          searchParams.get('end') || '',
          cutoff,
        ),
      },
      { headers: tedHeaders },
    )
  } catch (error) {
    return tedError(error)
  }
}
