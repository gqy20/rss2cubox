"""Query articles for comprehension debt and related topics."""
import os
import json
import psycopg
from dotenv import load_dotenv

load_dotenv(override=True)

db_url = os.getenv("LOCAL_DB_URL", "").strip()
if not db_url:
    print("NO_DB_URL")
else:
    with psycopg.connect(db_url) as conn:
        cur = conn.cursor()
        keywords = [
            "comprehension debt",
            "理解债务",
            "cognitive load",
            "认知负载",
            "code review",
            "可读性",
            "可理解性",
            "understandability score",
            "comprehensibility score",
            "code readability",
            "AI code understandability",
            "reviewing AI code",
            "stacked PR view",
            "Lubeno",
            "PR review workflow",
            "cognitive debt tool",
            "code review mental model",
            "AI contribution overwhelm",
            "AI code maintenance",
            "oversight burden",
            "cognitive overload",
            "AI assisted coding",
            "software engineering cognitive",
        ]
        clauses = []
        params = []
        for kw in keywords:
            clauses.append(
                "(title ILIKE %s OR description ILIKE %s OR hidden_signal ILIKE %s OR COALESCE(full_text, '') ILIKE %s)"
            )
            params.extend([f"%{kw}%", f"%{kw}%", f"%{kw}%", f"%{kw}%"])

        where = " OR ".join(clauses)

        cur.execute(
            f"""
            SELECT id, title, description, hidden_signal, evidence_strength,
                   publish_time
            FROM articles
            WHERE ({where})
            ORDER BY publish_time DESC
            LIMIT 100
        """,
            params,
        )
        rows = cur.fetchall()
        print(f"Total matches: {len(rows)}")
        for r in rows:
            print(
                json.dumps(
                    {
                        "id": r[0],
                        "title": r[1],
                        "description": (r[2] or "")[:400],
                        "hidden_signal": (r[3] or "")[:400],
                        "evidence_strength": r[4],
                        "publish_time": str(r[5]),
                    },
                    ensure_ascii=False,
                )
            )
