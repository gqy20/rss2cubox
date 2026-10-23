import { NextResponse } from 'next/server'
import { readPolicyChanges } from '../../../lib/journal-store'
export const dynamic = 'force-dynamic'

// 政策系列跨期比较结果（阶段变化纪要）。
export async function GET() {
  const headers = { 'Cache-Control': 'no-store' }
  try {
    return NextResponse.json({ data: await readPolicyChanges() }, { headers })
  } catch {
    return NextResponse.json(
      { error: '阶段变化暂时不可用' },
      { status: 503, headers },
    )
  }
}
