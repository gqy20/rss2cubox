import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'

describe('local stats route time semantics', () => {
  it('uses the same display-time fallback as the signal stream', () => {
    const source = readFileSync(
      path.join(process.cwd(), 'app/api/signals/local/stats/route.ts'),
      'utf8',
    )

    expect(source).toContain('DATE(COALESCE(publish_time, created_at)) = CURRENT_DATE')
    expect(source).toContain('WHERE COALESCE(publish_time, created_at) >= (CURRENT_DATE - INTERVAL')
    expect(source).not.toContain('WHERE DATE(created_at) = CURRENT_DATE')
    expect(source).not.toContain('DATE(created_at) as day')
  })
})
