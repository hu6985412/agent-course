"""W09 - 初始化库与表（连 root、不指定库，执行 CREATE DATABASE + 建表）。
用法: python init_db.py
"""
import os
import pymysql


def init(schema="schema.sql"):
    conn = pymysql.connect(
        host=os.getenv("FIN_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("FIN_DB_PORT", "3306")),
        user=os.getenv("FIN_DB_USER", "root"),
        password=os.getenv("FIN_DB_PASS", ""),
        charset="utf8mb4",
    )
    with open(schema, encoding="utf-8") as f:
        sql = f.read()
    try:
        with conn.cursor() as cur:
            # pymysql 的 execute 不支持 multi= 参数，按分号拆多条语句逐条执行
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if not stmt:
                    continue
                cur.execute(stmt)
        conn.commit()
        print("schema initialized: database fin_agent + 5 tables")
    finally:
        conn.close()


if __name__ == "__main__":
    init()
