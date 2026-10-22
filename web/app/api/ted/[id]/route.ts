import { NextRequest, NextResponse } from 'next/server'
import { readTedIssue, saveTedIssue } from '../../../../lib/ted-store'
import { canWriteTed } from '../../../../lib/ted-request'
import { tedBody, tedError, tedHeaders } from '../../../../lib/ted-api'
import { isTedId, TedValidationError } from '../../../../lib/ted'
export const dynamic = 'force-dynamic'
export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ id: string }> },
) {
  if (!canWriteTed(request))
    return NextResponse.json(
      { error: '该接口仅供后台生成报告使用。' },
      { status: 403, headers: tedHeaders },
    )
  try {
    const { id } = await context.params
    if (!isTedId(id) || !(await readTedIssue(id, true)))
      return NextResponse.json(
        { error: '这份报告不存在。' },
        { status: 404, headers: tedHeaders },
      )
    const body = await tedBody(request)
    if (
      !Number.isSafeInteger(body.version) ||
      !['save', 'publish'].includes(String(body.action))
    )
      throw new TedValidationError('保存版本或操作不正确。')
    return NextResponse.json(
      {
        data: await saveTedIssue(
          id,
          body.version as number,
          body.report,
          body.action === 'publish',
        ),
      },
      { headers: tedHeaders },
    )
  } catch (error) {
    return tedError(error)
  }
}
