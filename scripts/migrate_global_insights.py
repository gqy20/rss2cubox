"""迁移 Neon DB 的 global_insights 到本地 PostgreSQL"""
import json
import os
import psycopg

NEON_URL = os.getenv("NEON_DATABASE_URL", "").strip()
LOCAL_URL = os.getenv("LOCAL_DB_URL", "").strip()

def migrate():
    if not NEON_URL:
        print("NEON_DATABASE_URL 未设置")
        return

    if not LOCAL_URL:
        print("LOCAL_DB_URL 未设置")
        return

    # 从 Neon 读取所有 global_insights
    with psycopg.connect(NEON_URL, sslmode="require") as neon_conn:
        neon_cur = neon_conn.cursor()
        neon_cur.execute("""
            SELECT generated_at, data
            FROM global_insights
            ORDER BY generated_at DESC
        """)
        rows = neon_cur.fetchall()
        print(f"Neon 上有 {len(rows)} 条 global_insights")

    if not rows:
        print("没有数据需要迁移")
        return

    # 写入本地 DB
    with psycopg.connect(LOCAL_URL) as local_conn:
        local_cur = local_conn.cursor()

        # 确保表存在
        local_cur.execute("""
            CREATE TABLE IF NOT EXISTS global_insights (
                id           SERIAL PRIMARY KEY,
                generated_at TIMESTAMPTZ NOT NULL,
                data         JSONB NOT NULL
            )
        """)
        local_cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_global_insights_generated_at
            ON global_insights(generated_at DESC)
        """)

        imported = 0
        skipped = 0
        for generated_at, data in rows:
            # 检查是否已存在（根据 generated_at）
            local_cur.execute(
                "SELECT id FROM global_insights WHERE generated_at = %s",
                (generated_at,)
            )
            if local_cur.fetchone():
                skipped += 1
                continue

            data_json = json.dumps(data, ensure_ascii=False)
            local_cur.execute(
                """
                INSERT INTO global_insights (generated_at, data)
                VALUES (%s, %s)
                """,
                (generated_at, data_json)
            )
            imported += 1

        local_conn.commit()
        print(f"迁移完成：导入 {imported} 条，跳过 {skipped} 条已存在")

if __name__ == "__main__":
    migrate()
