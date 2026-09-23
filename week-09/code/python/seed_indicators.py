"""W09 - 字段字典冷启动（MVP 手动铺高频科目，不靠模型自动学）。
幂等：已存在则更新 aliases 等字段。
用法: python seed_indicators.py [indicators_seed.json]
"""
import json
import sys

import db


def seed(path="indicators_seed.json"):
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    conn = db.get_conn()
    try:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    """INSERT INTO fin_indicators
                       (code,name,aliases,unit_standard,unit_convert,confusing_group,requires_modifier_guard)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)
                       ON DUPLICATE KEY UPDATE
                         name=VALUES(name),
                         aliases=VALUES(aliases),
                         unit_standard=VALUES(unit_standard),
                         unit_convert=VALUES(unit_convert),
                         confusing_group=VALUES(confusing_group),
                         requires_modifier_guard=VALUES(requires_modifier_guard)""",
                    (
                        r["code"],
                        r["name"],
                        json.dumps(r["aliases"], ensure_ascii=False),
                        r["unit_standard"],
                        r["unit_convert"],
                        r["confusing_group"],
                        r["requires_modifier_guard"],
                    ),
                )
        conn.commit()
        print(f"seeded/updated {len(rows)} indicators")
    finally:
        conn.close()


if __name__ == "__main__":
    seed(sys.argv[1] if len(sys.argv) > 1 else "indicators_seed.json")
