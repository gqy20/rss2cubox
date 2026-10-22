import { NextRequest, NextResponse } from 'next/server'
import { createTedIssue, listTedAudienceIssues } from '../../../lib/ted-store'
import { tedReadingSummary } from '../../../lib/ted-reader'
import { canWriteTed } from '../../../lib/ted-request'
import { tedBody, tedError, tedHeaders } from '../../../lib/ted-api'
import { TedValidationError } from '../../../lib/ted'
export const dynamic = 'force-dynamic'
export async function GET() {
  try {
    const issues = await listTedAudienceIssues()
    return NextResponse.json(
      { data: issues.map(tedReadingSummary) },
      { headers: tedHeaders },
    )
  } catch (error) {
    return tedError(error)
  }
}

export async function POST(request: NextRequest) {
  if (!canWriteTed(request))
    return NextResponse.json(
      { error: '该接口仅供后台生成报告使用。' },
      { status: 403, headers: tedHeaders },
    )
  try {
    const body = await tedBody(request)
    if (typeof body.start !== 'string' || typeof body.end !== 'string')
      throw new TedValidationError('请选择覆盖日期。')
    return NextResponse.json(
      { data: await createTedIssue(body.start, body.end) },
      { status: 201, headers: tedHeaders },
    )
  } catch (error) {
    return tedError(error)
  }
}
