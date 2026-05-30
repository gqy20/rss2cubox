"""Query articles for prediction 39 review."""
import os
import json
import psycopg

db_url = os.getenv("LOCAL_DB_URL", "").strip()
if not db_url:
    print("NO_DB_URL")
else:
    with psycopg.connect(db_url) as conn:
        cur = conn.cursor()
        keywords = [
            "self-driving laboratory",
            "CoScientist",
            "Eve Laboratory",
            "automated hypothesis generation",
            "lab automation open source",
            "research automation GitHub",
            "autonomous experiment",
            "AI experiment automation",
            "lab-on-cloud",
            "scientific pipeline reproducible",
        ]
        clauses = []
        params = []
        for kw in keywords:
            clauses.append("(title ILIKE %s OR description ILIKE %s)")
            params.extend([f"%{kw}%", f"%{kw}%"])
        where = " OR ".join(clauses)
        params.extend(["2026-05-19 21:30:22", "2026-05-26 21:30:22"])

        cur.execute(f"""
            SELECT id, title, url, publish_time, source
            FROM articles
            WHERE ({where})
              AND publish_time >= %s::timestamptz
              AND publish_time <= %s::timestamptz
            ORDER BY publish_time DESC
            LIMIT 20
        """, params)
        rows = cur.fetchall()
        if not rows:
            print("NO_ARTICLES_FOUND")
        else:
            for r in rows:
                print(json.dumps({
                    "id": r[0],
                    "title": r[1],
                    "url": r[2],
                    "publish_time": str(r[3]),
                    "source": r[4],
                }, ensure_ascii=False))
