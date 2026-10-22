// Opt-in real PostgreSQL check. All mutations are confined to a fresh temporary schema.
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'
import {
  createTedIssue,
  listTedIssues,
  listTedRevisions,
  readTedIssue,
  readTedMaterials,
  saveTedIssue,
} from '../../lib/ted-store'

const database = process.env.TED_TEST_DATABASE_URL
describe.skipIf(!database)('TED PostgreSQL lifecycle', () => {
  const schema = 'ted_test_' + randomUUID().replaceAll('-', '')
  let admin: Pool, isolated: Pool
  const globalDb = globalThis as typeof globalThis & { journalPool?: Pool }
  const previous = globalDb.journalPool
  const previousUrl = process.env.DATABASE_URL

  beforeAll(async () => {
    process.env.DATABASE_URL = database
    admin = new Pool({ connectionString: database, max: 1 })
    await admin.query(`CREATE SCHEMA ${schema}`)
    isolated = new Pool({
      connectionString: database,
      max: 4,
      options: `-c search_path=${schema},public`,
    })
    globalDb.journalPool = isolated
    for (const table of [
      'articles',
      'policy_documents',
      'signal_clusters',
      'signal_cluster_articles',
    ])
      await isolated.query(
        `CREATE TABLE ${table} (LIKE public.${table} INCLUDING DEFAULTS)`,
      )
    await isolated.query(`INSERT INTO articles
      (id,source_type,source_feed_id,source_feed_name,title,url,publish_time,created_at,importance_score,hidden_signal)
      VALUES ('ted-test-article','test','source','测试信源','测试文章','https://example.org/test',
        '2026-09-18T12:00:00+08:00','2026-09-18T13:00:00+08:00',4,'用于验证资料快照')`)
    await isolated.query(`INSERT INTO articles
      (id,source_type,title,url,publish_time,created_at,hidden_signal)
      VALUES ('late-arrival','test','晚入库文章','https://example.org/late',
        '2026-09-18T12:00:00+08:00','2026-09-20T13:00:00+08:00','不应进入早期快照')`)
    await isolated.query(`INSERT INTO policy_documents
      (id,site_key,site_name,title,url,published_at,first_seen_at,enriched_at,ai_relevance,summary)
      VALUES ('ted-test-policy','government','测试机构','测试政策','https://example.org/policy',
        '2026-09-17T12:00:00+08:00','2026-09-17T13:00:00+08:00','2026-09-18T13:00:00+08:00',4,'政策摘要')`)
  })
  afterAll(async () => {
    globalDb.journalPool = previous
    if (previousUrl === undefined) delete process.env.DATABASE_URL
    else process.env.DATABASE_URL = previousUrl
    await isolated?.end()
    if (admin) {
      await admin.query(`DROP SCHEMA IF EXISTS ${schema} CASCADE`)
      await admin.end()
    }
  })

  it('uses a real cutoff, creates a draft, publishes atomically and isolates later edits', async () => {
    const packet = await readTedMaterials(
      '2026-09-12',
      '2026-09-18',
      '2026-09-19T00:00:00Z',
    )
    expect(packet.coverage.articles).toBe(1)
    expect(packet.coverage.policies).toBe(1)
    expect(packet.materials).toHaveLength(2)
    const created = (await createTedIssue('2026-09-12', '2026-09-18'))!
    expect(created.report.topics.length).toBeGreaterThan(0)
    expect(await readTedIssue(created.id)).toBeNull()
    expect(await listTedIssues()).toEqual([])
    const report = created.report
    report.title = '测试报告'
    report.intro = '测试导读'
    report.topics = report.topics.slice(0, 1)
    report.topics[0].claim = '测试判断 [1]'
    report.topics[0].host_notes = '仅内部可见'
    for (const source of report.topics[0].sources)
      source.reason = '测试引用理由'
    const published = (await saveTedIssue(
      created.id,
      created.version,
      report,
      true,
    ))!
    expect((await readTedIssue(created.id))!.report.topics[0].host_notes).toBe(
      '',
    )
    expect(
      (await readTedIssue(created.id, true))!.report.topics[0].host_notes,
    ).toBe('仅内部可见')
    expect(await listTedRevisions(created.id)).toHaveLength(1)
    expect((await listTedIssues())[0].report.topics[0]).not.toHaveProperty(
      'host_notes',
    )
    report.title = '未发布修订'
    const changed = (await saveTedIssue(
      created.id,
      published.version,
      report,
      false,
    ))!
    expect((await readTedIssue(created.id))!.report.title).toBe('测试报告')
    expect((await readTedIssue(created.id, true))!.report.title).toBe(
      '未发布修订',
    )
    await expect(
      saveTedIssue(created.id, published.version, report, true),
    ).rejects.toThrow('其他窗口')
    await saveTedIssue(created.id, changed.version, report, true)
    expect((await readTedIssue(created.id))!.report.title).toBe('未发布修订')
    expect(await listTedRevisions(created.id)).toHaveLength(2)
  })
})
